"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, LoaderCircle, X } from "lucide-react";

interface PipelineJob {
  id: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  error?: string;
}

const steps = [
  { kind: "collect_sources", title: "1. Collecte", text: "Récupère Reddit, forums, SERP/PAA, Trustpilot et GSC.", action: "collection" },
  { kind: "transform_signals", title: "2. Questions", text: "Nettoie les signaux et les transforme en questions utilisateurs.", action: "launch" },
  { kind: "cluster_questions", title: "3. Clusters", text: "Regroupe les questions par intention avec embeddings.", action: "launch" },
  { kind: "build_dataset", title: "4. Dataset", text: "Construit le corpus candidat et exécute l’échantillon choisi.", action: "dataset" },
  { kind: "validate_dataset", title: "5. Validation", text: "Réexécute les exemples acceptés sur 3 ou 5 runs.", action: "dataset" },
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
  onOpenReview: () => void;
  onOpenExports: () => void;
}

export function PipelineModal({ projectId, onClose, onOpenCollection, onOpenDataset, onOpenReview, onOpenExports }: PipelineModalProps) {
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!projectId) return;
    const response = await fetch(`/api/jobs?projectId=${encodeURIComponent(projectId)}`, { cache: "no-store" });
    if (response.ok) setJobs((await response.json()).jobs ?? []);
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

  function openAction(action: string) {
    if (action === "collection") onOpenCollection();
    if (action === "dataset") onOpenDataset();
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
            const job = latest(step.kind);
            const launchable = launchableKinds.has(step.kind);
            return (
              <article key={step.kind}>
                <div className="pipeline-index">
                  {job?.status === "completed" ? <CheckCircle2 size={19} /> : job?.status === "running" ? <LoaderCircle className="spin" size={19} /> : <Circle size={19} />}
                </div>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                  {job && <small className={`job-${job.status}`}>{job.status} · {job.progress}%{job.error ? ` · ${job.error}` : ""}</small>}
                  {!job && <small>Non lancé</small>}
                </div>
                <button className="secondary" onClick={() => launchable ? void launch(step.kind) : openAction(step.action)}>
                  {launchable ? (job ? "Relancer" : "Lancer") : step.action === "collection" ? "Configurer" : step.action === "dataset" ? "Ouvrir" : step.action === "review" ? "Réviser" : "Exporter"}<ArrowRight size={14} />
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
