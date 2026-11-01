"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, LoaderCircle, X } from "lucide-react";

interface PipelineJob {
  id: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  output?: Record<string, unknown>;
  error?: string;
}

interface WorkflowMetrics {
  signals: number;
  questions: number;
  clusters: number;
  datasets: number;
  observations: number;
  validations: number;
  approved: number;
}

const steps = [
  { kind: "collect_sources", title: "1. Collecte", text: "Récupère Reddit, forums, SERP/PAA, Trustpilot et GSC.", action: "collection" },
  { kind: "transform_signals", title: "2. Questions", text: "Nettoie les signaux et les transforme en questions utilisateurs.", action: "launch" },
  { kind: "cluster_questions", title: "3. Clusters", text: "Regroupe les questions par intention avec embeddings.", action: "launch" },
  { kind: "build_dataset", title: "4. Dataset", text: "Construit le corpus candidat et exécute l’échantillon choisi.", action: "dataset" },
  { kind: "validate_dataset", title: "5. Validation", text: "Réexécute les exemples acceptés sur 3 ou 5 runs.", action: "validation" },
  { kind: "reverse_engineer", title: "6. Reverse engineering", text: "Parcours « reconstruction » : reconstruit des prompts uniquement à partir des fan-outs réellement observés (cibles à sélectionner). Distinct de l'étape 4, qui génère depuis les signaux utilisateurs.", action: "launch" },
  { kind: "manual_review", title: "7. Revue humaine", text: "Approuve, modifie ou rejette les prompts avant export.", action: "review" },
  { kind: "semactic_export", title: "8. Export", text: "Exporte uniquement les prompts acceptés et approuvés.", action: "export" },
];

const launchableKinds = new Set(["transform_signals", "cluster_questions", "reverse_engineer"]);

interface TargetObservation {
  id: string;
  prompt_text: string;
  provider: string;
  engine: string;
  observed_at: string;
  fan_out_count: number;
}

interface PipelineModalProps {
  projectId: string | null;
  onClose: () => void;
  onOpenCollection: () => void;
  onOpenDataset: () => void;
  onOpenValidation: () => void;
  onOpenReview: () => void;
  onOpenExports: () => void;
}

export function PipelineModal({ projectId, onClose, onOpenCollection, onOpenDataset, onOpenValidation, onOpenReview, onOpenExports }: PipelineModalProps) {
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [metrics, setMetrics] = useState<WorkflowMetrics>({ signals: 0, questions: 0, clusters: 0, datasets: 0, observations: 0, validations: 0, approved: 0 });
  const [message, setMessage] = useState("");
  const [rePanel, setRePanel] = useState(false);
  const [targets, setTargets] = useState<TargetObservation[]>([]);
  const [selectedTargets, setSelectedTargets] = useState<string[]>([]);
  const [maxCandidates, setMaxCandidates] = useState(3);
  const [validationRuns, setValidationRuns] = useState(3);
  const [executionCeiling, setExecutionCeiling] = useState(0);

  const load = useCallback(async () => {
    if (!projectId) return;
    const [jobsResponse, dashboardResponse] = await Promise.all([
      fetch(`/api/jobs?projectId=${encodeURIComponent(projectId)}`, { cache: "no-store" }),
      fetch(`/api/dashboard?projectId=${encodeURIComponent(projectId)}`, { cache: "no-store" }),
    ]);
    if (jobsResponse.ok) setJobs((await jobsResponse.json()).jobs ?? []);
    if (dashboardResponse.ok) setMetrics((await dashboardResponse.json()).metrics ?? { signals: 0, questions: 0, clusters: 0, datasets: 0, observations: 0, validations: 0, approved: 0 });
  }, [projectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    const interval = window.setInterval(() => void load(), 5000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [load]);

  async function launch(kind: string) {
    if (!projectId) { setMessage("Créez d'abord un workspace Supabase."); return; }
    if (kind === "reverse_engineer") {
      setMessage("Chargement des observations éligibles…");
      const response = await fetch(`/api/observations?projectId=${encodeURIComponent(projectId)}`, { cache: "no-store" });
      const data = await response.json();
      setTargets(response.ok ? data.observations ?? [] : []);
      setSelectedTargets([]);
      setExecutionCeiling(0);
      setRePanel(true);
      setMessage(response.ok ? "" : data.error ?? "Chargement impossible.");
      return;
    }
    setMessage("Création du job…");
    const response = await fetch("/api/pipeline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, stage: kind }) });
    const data = await response.json();
    setMessage(response.ok ? "Job ajouté à la file du worker." : data.error ?? "Création impossible.");
    if (response.ok) await load();
  }

  const maxExecutions = selectedTargets.length * maxCandidates * validationRuns;
  const effectiveCeiling = Math.max(executionCeiling, maxExecutions);

  function toggleTarget(id: string) {
    setSelectedTargets((current) => {
      if (current.includes(id)) return current.filter((value) => value !== id);
      if (current.length >= 10) return current; // le worker borne max_targets à 10
      return [...current, id];
    });
  }

  async function launchReverseEngineer() {
    if (!projectId) return;
    setMessage("Création du job de reconstruction…");
    const response = await fetch("/api/pipeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId,
        stage: "reverse_engineer",
        input: {
          target_observation_ids: selectedTargets,
          max_targets: selectedTargets.length,
          max_candidates_per_cluster: maxCandidates,
          validation_runs: validationRuns,
          max_validation_executions: effectiveCeiling,
        },
      }),
    });
    const data = await response.json();
    setMessage(response.ok ? "Job de reconstruction ajouté à la file." : data.error ?? "Création impossible.");
    if (response.ok) { setRePanel(false); await load(); }
  }

  function latest(kind: string) {
    return jobs.find((job) => job.kind === kind);
  }

  function isDone(kind: string) {
    const job = latest(kind);
    if (job?.status === "completed") return true;
    if (kind === "collect_sources") return metrics.signals > 0;
    if (kind === "transform_signals") return metrics.questions > 0;
    if (kind === "cluster_questions") return metrics.clusters > 0;
    if (kind === "build_dataset") return metrics.observations > 0;
    if (kind === "validate_dataset") return metrics.validations > 0;
    if (kind === "manual_review") return metrics.approved > 0;
    if (kind === "semactic_export") return false;
    return false;
  }

  function visibleJob(kind: string) {
    if (kind === "cluster_questions") return latest("cluster_questions") ?? latest("transform_signals");
    return latest(kind);
  }

  function statusLabel(kind: string) {
    const job = visibleJob(kind);
    if (isDone(kind)) return "Terminé";
    if (job?.status === "running" || job?.status === "pending") return "En cours";
    if (job?.status === "failed") return "Échec";
    if (job?.status === "cancelled") return "Annulé";
    return "Non lancé";
  }

  function openAction(action: string) {
    if (action === "collection") onOpenCollection();
    if (action === "dataset") onOpenDataset();
    if (action === "validation") onOpenValidation();
    if (action === "review") onOpenReview();
    if (action === "export") onOpenExports();
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal docs-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div><span className="eyebrow">PIPELINE DE PRODUCTION</span><h2>Les 8 étapes du workflow</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <div className="pipeline-steps">
          {steps.map((step) => {
            const job = visibleJob(step.kind);
            const launchable = launchableKinds.has(step.kind);
            const done = isDone(step.kind);
            const running = job?.status === "running" || job?.status === "pending";
            const label = done ? "Terminé" : launchable ? (step.kind === "transform_signals" ? "Préparer" : "Lancer") : step.action === "collection" ? "Configurer" : step.action === "dataset" ? "Ouvrir" : step.action === "review" ? "Réviser" : "Exporter";
            return (
              <article key={step.kind}>
                <div className="pipeline-index">
                  {done ? <CheckCircle2 size={19} /> : running ? <LoaderCircle className="spin" size={19} /> : <Circle size={19} />}
                </div>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                  <small className={`job-${done ? "completed" : job?.status ?? "pending"}`}>{statusLabel(step.kind)}{job && !done ? ` · ${job.progress}%` : ""}{job?.error && !done ? ` · ${job.error}` : ""}</small>
                </div>
                <button className="secondary" disabled={done && step.kind !== "collect_sources" || running} onClick={() => launchable ? void launch(step.kind === "transform_signals" ? "prepare_questions" : step.kind) : openAction(step.action)}>
                  {label}<ArrowRight size={14} />
                </button>
              </article>
            );
          })}
        </div>
        {rePanel && (
          <div className="export-item" style={{ padding: "1rem" }}>
            <strong>Cibles de reconstruction — observations avec fan-outs rapportés par le provider</strong>
            <p>Seules les observations réelles du projet sont éligibles. Le prompt cible est exclu de son propre contexte ICL et la validation réexécute chaque candidat sur le même moteur.</p>
            {targets.length === 0 && <p>Aucune observation éligible : exécutez d&apos;abord des prompts via l&apos;étape 4 (build_dataset) pour produire des fan-outs Bright Data.</p>}
            <div style={{ maxHeight: "16rem", overflowY: "auto", margin: "0.75rem 0" }}>
              {targets.map((target) => (
                <label key={target.id} style={{ display: "flex", gap: "0.5rem", alignItems: "center", padding: "0.3rem 0" }}>
                  <input type="checkbox" checked={selectedTargets.includes(target.id)} onChange={() => toggleTarget(target.id)} />
                  <span style={{ flex: 1 }}>{target.prompt_text}</span>
                  <small>{target.engine} · {target.fan_out_count} fan-outs · {String(target.observed_at).slice(0, 10)}</small>
                </label>
              ))}
            </div>
            <div className="form-row">
              <label>Candidats / cible<input type="number" min={3} max={5} value={maxCandidates} onChange={(event) => setMaxCandidates(Number(event.target.value))} /></label>
              <label>Runs de validation<input type="number" min={1} max={4} value={validationRuns} onChange={(event) => setValidationRuns(Number(event.target.value))} /></label>
              <label>Plafond d&apos;exécutions<input type="number" min={maxExecutions} value={effectiveCeiling} onChange={(event) => setExecutionCeiling(Number(event.target.value))} /></label>
            </div>
            <small>Plan borné : {selectedTargets.length} cible(s) (max 10) × {maxCandidates} candidats × {validationRuns} run(s) = maximum planifié de {maxExecutions} exécutions payantes ; la validation adaptative peut en exécuter moins. Le statut « validated » exige ≥ 3 runs et une stabilité ≥ 0,65.</small>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
              <button className="primary" disabled={!selectedTargets.length || effectiveCeiling < maxExecutions} onClick={() => void launchReverseEngineer()}>Lancer la reconstruction</button>
              <button className="secondary" onClick={() => setRePanel(false)}>Fermer</button>
            </div>
          </div>
        )}
        {message && <p className="import-status">{message}</p>}
        <div className="pipeline-note">La liste se rafraîchit toutes les 5 secondes. La collecte, le dataset, la revue et l’export utilisent leurs écrans dédiés.</div>
      </div>
    </div>
  );
}
