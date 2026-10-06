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
  { kind: "reverse_engineer", title: "6. Reverse engineering", text: "Reconstruit des prompts à partir des fan-outs observés.", action: "launch" },
  { kind: "manual_review", title: "7. Revue humaine", text: "Approuve, modifie ou rejette les prompts avant export.", action: "review" },
  { kind: "semactic_export", title: "8. Export", text: "Exporte uniquement les prompts acceptés et approuvés.", action: "export" },
];

const launchableKinds = new Set(["transform_signals", "cluster_questions", "reverse_engineer"]);

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
    setMessage("Création du job…");
    const response = await fetch("/api/pipeline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, stage: kind }) });
    const data = await response.json();
    setMessage(response.ok ? "Job ajouté à la file du worker." : data.error ?? "Création impossible.");
    if (response.ok) await load();
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
        {message && <p className="import-status">{message}</p>}
        <div className="pipeline-note">La liste se rafraîchit toutes les 5 secondes. La collecte, le dataset, la revue et l’export utilisent leurs écrans dédiés.</div>
      </div>
    </div>
  );
}
