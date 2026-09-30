"use client";

import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, LoaderCircle, X } from "lucide-react";

interface PipelineJob {
  id: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  error?: string;
}

const steps = [
  { stage: "prepare_questions", kind: "transform_signals", title: "Préparer les questions", text: "Transforme les signaux puis lance automatiquement le clustering." },
  { stage: "cluster_questions", kind: "cluster_questions", title: "Recalculer les clusters", text: "Embeddings, regroupement sémantique et sélection des représentants." },
  { stage: "reverse_engineer", kind: "reverse_engineer", title: "Reverse engineering", text: "Reconstruit de nouveaux prompts depuis les exemples acceptés." },
];

export function PipelineModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [message, setMessage] = useState("");

  async function load() {
    if (!projectId) return;
    const response = await fetch(`/api/pipeline?projectId=${encodeURIComponent(projectId)}`);
    if (response.ok) setJobs((await response.json()).jobs ?? []);
  }

  useEffect(() => {
    if (!projectId) return;
    fetch(`/api/pipeline?projectId=${encodeURIComponent(projectId)}`)
      .then((response) => response.ok ? response.json() : { jobs: [] })
      .then((data) => setJobs(data.jobs ?? []));
  }, [projectId]);

  async function launch(stage: string) {
    if (!projectId) { setMessage("Créez d'abord un workspace Supabase."); return; }
    setMessage("Création du job…");
    const response = await fetch("/api/pipeline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, stage }) });
    const data = await response.json();
    setMessage(response.ok ? "Job ajouté à la file du worker." : data.error ?? "Création impossible.");
    if (response.ok) await load();
  }

  function latest(kind: string) {
    return jobs.find((job) => job.kind === kind);
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><div className="modal pipeline-modal" onMouseDown={(event) => event.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">PIPELINE DE PRODUCTION</span><h2>Des signaux au reverse engineering</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><div className="pipeline-steps">{steps.map((step, index) => { const job = latest(step.kind); return <article key={step.stage}><div className="pipeline-index">{job?.status === "completed" ? <CheckCircle2 size={19} /> : job?.status === "running" ? <LoaderCircle className="spin" size={19} /> : <Circle size={19} />}</div><div><span>ÉTAPE {index + 1}</span><h3>{step.title}</h3><p>{step.text}</p>{job && <small className={`job-${job.status}`}>{job.status} · {job.progress}%{job.error ? ` · ${job.error}` : ""}</small>}</div><button className="secondary" onClick={() => void launch(step.stage)}>{job ? "Relancer" : "Lancer"}<ArrowRight size={14} /></button></article>; })}</div>{message && <p className="import-status">{message}</p>}<div className="pipeline-note">Le worker Python doit être actif pour traiter les jobs. L&apos;étape 1 enchaîne automatiquement la transformation et le clustering.</div></div></div>;
}
