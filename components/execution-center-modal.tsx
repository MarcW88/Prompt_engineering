"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertCircle, CheckCircle2, CircleSlash, Clock3, LoaderCircle, RefreshCw, Trash2, X } from "lucide-react";

interface ExecutionJob {
  id: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  output?: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  heartbeat_at?: string | null;
}

const kindLabels: Record<string, string> = {
  collect_sources: "Collecte des sources",
  transform_signals: "Transformation en questions",
  cluster_questions: "Clustering sémantique",
  build_dataset: "Construction et exécution du dataset",
  validate_dataset: "Validation répétée",
  reverse_engineer: "Reverse engineering",
};

const statusLabels: Record<ExecutionJob["status"], string> = {
  pending: "En attente",
  running: "En cours",
  completed: "Terminé",
  failed: "Échoué",
  cancelled: "Annulé",
};

function duration(from: string | null | undefined, to?: string | null) {
  if (!from) return "—";
  const end = to ? new Date(to).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((end - new Date(from).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function estimate(job: ExecutionJob) {
  if (job.status !== "running" || !job.started_at || job.progress <= 0) return "—";
  const elapsed = Date.now() - new Date(job.started_at).getTime();
  const remaining = Math.round(elapsed * (100 - job.progress) / job.progress / 1000);
  if (remaining <= 0 || !Number.isFinite(remaining)) return "—";
  return remaining < 60 ? `≈ ${remaining}s` : `≈ ${Math.floor(remaining / 60)}m ${remaining % 60}s`;
}

const orderedKinds = ["collect_sources", "transform_signals", "cluster_questions", "build_dataset", "validate_dataset", "reverse_engineer"];

function nextStep(jobs: ExecutionJob[]) {
  const active = jobs.find((job) => job.status === "running" || job.status === "pending");
  if (active) return `En cours : ${kindLabels[active.kind] ?? active.kind}. Vous pouvez suivre ou annuler cette exécution ci-dessous.`;
  const latestByKind = new Map(jobs.map((job) => [job.kind, job]));
  const nextKind = orderedKinds.find((kind) => latestByKind.get(kind)?.status !== "completed");
  if (!nextKind) return "Prochaine étape : ouvrez Revue manuelle, puis exportez les prompts approuvés.";
  const actions: Record<string, string> = {
    collect_sources: "Prochaine étape : ouvrez Nouvelle collecte.",
    transform_signals: "Prochaine étape : Piloter le workflow → Préparer les questions.",
    cluster_questions: "Prochaine étape : Piloter le workflow → Préparer les questions (le clustering se lance automatiquement).",
    build_dataset: "Prochaine étape : ouvrez Dataset Builder.",
    validate_dataset: "Prochaine étape : ouvrez Dataset Builder et lancez la validation à 3 runs.",
    reverse_engineer: "Prochaine étape : Piloter le workflow → Reverse engineering.",
  };
  return actions[nextKind];
}

function details(output: Record<string, unknown> | undefined) {
  if (!output) return "";
  const parts = [
    ["selected", "sélectionnés"],
    ["executions", "exécutions"],
    ["questions", "questions"],
    ["clusters", "clusters"],
    ["signals", "signaux"],
    ["candidates", "candidats"],
    ["reconstructed", "reconstruits"],
    ["completed_runs", "runs"],
    ["language_rejected", "langues filtrées"],
  ];
  return parts.filter(([key]) => typeof output[key] === "number").map(([key, label]) => `${output[key]} ${label}`).join(" · ");
}

function sourceDetails(output: Record<string, unknown> | undefined) {
  const report = output?.source_report;
  if (!report || typeof report !== "object") return "";
  return Object.entries(report as Record<string, { collected?: number; errors?: number; skipped?: unknown }>).map(([source, value]) => {
    const skipped = typeof value.skipped === "string" ? ` · ${value.skipped}` : typeof value.skipped === "object" && value.skipped ? ` · ${Object.values(value.skipped).join(" · ")}` : "";
    return `${source}: ${value.collected ?? 0} collecté(s), ${value.errors ?? 0} erreur(s)${skipped}`;
  }).join(" | ");
}

export function ExecutionCenterModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [jobs, setJobs] = useState<ExecutionJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/jobs?projectId=${encodeURIComponent(projectId)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Chargement impossible.");
      setJobs(data.jobs ?? []);
      setUpdatedAt(new Date());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    const interval = window.setInterval(() => void load(), 5000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [load]);

  const running = jobs.filter((job) => job.status === "running" || job.status === "pending").length;

  async function cancelJob(jobId: string) {
    setCancelling(jobId);
    setError("");
    try {
      const response = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Annulation impossible.");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Annulation impossible.");
    } finally {
      setCancelling(null);
    }
  }

  async function removeJob(jobId: string) {
    setRemoving(jobId);
    setError("");
    try {
      const response = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Suppression impossible.");
      setJobs((current) => current.filter((job) => job.id !== jobId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Suppression impossible.");
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal execution-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className="eyebrow">EXÉCUTIONS</span>
            <h2>Progression du workflow</h2>
          </div>
          <button type="button" className="icon-button" onClick={() => void load()} aria-label="Actualiser"><RefreshCw size={18} className={loading ? "spin" : ""} /></button>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <div className="execution-summary">
          <span><Activity size={16} /> {running} job{running > 1 ? "s" : ""} actif{running > 1 ? "s" : ""}</span>
          <small>{updatedAt ? `Actualisé à ${updatedAt.toLocaleTimeString("fr-FR")}` : "Actualisation…"}</small>
        </div>
        <div className="next-step"><strong>À faire maintenant</strong><p>{nextStep(jobs)}</p></div>
        {error && <p className="form-error">{error}</p>}
        <div className="execution-list">
          {jobs.map((job) => (
            <article key={job.id} className={`execution-item job-${job.status}`}>
              <div className="execution-title">
                {job.status === "completed" ? <CheckCircle2 size={18} /> : job.status === "failed" || job.status === "cancelled" ? <AlertCircle size={18} /> : <LoaderCircle size={18} className={job.status === "running" ? "spin" : ""} />}
                <div>
                  <strong>{kindLabels[job.kind] ?? job.kind}</strong>
                  <small>{statusLabels[job.status]} · démarré {job.started_at ? new Date(job.started_at).toLocaleTimeString("fr-FR") : "—"}</small>
                </div>
              </div>
              <div className="execution-bar"><span style={{ width: `${job.progress}%` }} /></div>
              <div className="execution-meta">
                <span>{job.progress}%</span>
                <span><Clock3 size={13} /> {duration(job.started_at, job.completed_at)}</span>
                <span>Reste {estimate(job)}</span>
                {(job.status === "running" || job.status === "pending") && (
                  <button type="button" className="cancel-button" onClick={() => void cancelJob(job.id)} disabled={cancelling === job.id}>
                    <CircleSlash size={13} /> {cancelling === job.id ? "Annulation…" : "Annuler"}
                  </button>
                )}
                {!(job.status === "running" || job.status === "pending") && (
                  <button type="button" className="remove-button" onClick={() => void removeJob(job.id)} disabled={removing === job.id} aria-label="Retirer ce run">
                    <Trash2 size={13} /> {removing === job.id ? "Suppression…" : "Retirer"}
                  </button>
                )}
              </div>
              {typeof job.output?.stage === "string" && <small className="execution-stage">{job.output.stage}</small>}
              {details(job.output) && <small className="execution-output">{details(job.output)}</small>}
              {sourceDetails(job.output) && <small className="execution-output">{sourceDetails(job.output)}</small>}
              {job.error && <p className="form-error">{job.error}</p>}
            </article>
          ))}
          {jobs.length === 0 && <div className="empty-state"><Activity size={28} /><p>Aucun job lancé dans ce workspace.</p></div>}
        </div>
      </section>
    </div>
  );
}
