"use client";

import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Play, ShieldCheck, X } from "lucide-react";

interface Dataset { id: string; name: string; status: string; statistics?: Record<string, unknown>; created_at: string }
interface ValidationJob { id: string; kind: string; status: string; progress: number; output?: Record<string, unknown>; error?: string | null; created_at: string }

export function ValidationModal({ projectId, onClose, onJobQueued }: { projectId: string | null; onClose: () => void; onJobQueued?: () => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [jobs, setJobs] = useState<ValidationJob[]>([]);
  const [message, setMessage] = useState("");
  const [hasLoaded, setHasLoaded] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    const projectIdValue = projectId;
    let active = true;
    async function loadData() {
      const [datasetsResponse, jobsResponse] = await Promise.all([
        fetch(`/api/datasets?projectId=${encodeURIComponent(projectIdValue)}`),
        fetch(`/api/jobs?projectId=${encodeURIComponent(projectIdValue)}`),
      ]);
      const datasetsData = datasetsResponse.ok ? await datasetsResponse.json() : { datasets: [] };
      const jobsData = jobsResponse.ok ? await jobsResponse.json() : { jobs: [] };
      const list = (datasetsData.datasets ?? []).filter((dataset: Dataset) => dataset.status === "ready");
      if (!active) return;
      setDatasets(list);
      setSelectedDatasetId((current) => {
        if (current && list.some((dataset: Dataset) => dataset.id === current)) return current;
        const withAccepted = list.find((dataset: Dataset) => Number(dataset.statistics?.accepted ?? 0) > 0);
        return withAccepted?.id || list[0]?.id || "";
      });
      setJobs((jobsData.jobs ?? []).filter((job: ValidationJob) => job.kind === "validate_dataset"));
      setHasLoaded(true);
    }
    void loadData();
    const interval = window.setInterval(() => void loadData(), 5000);
    return () => { active = false; window.clearInterval(interval); };
  }, [projectId]);

  async function validate(targetRuns: 3 | 5) {
    if (!projectId || !selectedDatasetId) { setMessage("Sélectionne un dataset."); return; }
    setMessage(`Planification de la vague à ${targetRuns} runs…`);
    const response = await fetch("/api/datasets/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, datasetId: selectedDatasetId, targetRuns, limit: targetRuns === 3 ? 100 : 50 }),
    });
    const data = await response.json();
    setMessage(response.ok ? `Vague ${targetRuns} runs ajoutée à la file du worker.` : data.error ?? "Planification impossible.");
    if (response.ok) window.setTimeout(() => onJobQueued?.(), 700);
  }

  const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId);
  const acceptedCount = typeof selectedDataset?.statistics?.accepted === "number" ? selectedDataset.statistics.accepted : 0;
  const sampledCount = typeof selectedDataset?.statistics?.sampled === "number" ? selectedDataset.statistics.sampled : 0;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal docs-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div><span className="eyebrow">VALIDATION</span><h2>Stabiliser les prompts acceptés</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="export-intro">Sélectionne le dataset à valider, puis lance une vague de 3 runs. Les prompts acceptés au screening seront ré-exécutés pour mesurer la stabilité.</p>
        {hasLoaded && datasets.length === 0 && <p className="import-status">Aucun dataset disponible. Construis d’abord un dataset depuis le Dataset Builder.</p>}
        {datasets.length > 0 && (
          <label>Dataset<select value={selectedDatasetId} onChange={(event) => setSelectedDatasetId(event.target.value)}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.status}</option>)}</select></label>
        )}
        {selectedDataset && (
          <div className="builder-guide">
            <strong>État du dataset</strong>
            <p>{sampledCount} prompts sélectionnés au screening · {acceptedCount} acceptés.</p>
            {acceptedCount === 0 && <p className="warning">Aucun prompt n’a été accepté. Relance le Dataset Builder ou baisse le seuil de qualité.</p>}
          </div>
        )}
        <div className="form-row compact">
          <button type="button" className="primary" disabled={!selectedDatasetId || acceptedCount === 0} onClick={() => void validate(3)}><Play size={16} /> Valider à 3 runs</button>
          <button type="button" className="secondary" disabled={!selectedDatasetId || acceptedCount === 0} onClick={() => void validate(5)}><Play size={16} /> Valider à 5 runs</button>
        </div>
        {message && <p className="import-status">{message}</p>}
        {jobs.length > 0 && (
          <div className="validation-jobs">
            <h4><ShieldCheck size={16} /> Jobs de validation</h4>
            {jobs.map((job) => (
              <div key={job.id} className={`validation-job ${job.status}`}>
                <span>{job.status === "completed" ? <CheckCircle2 size={16} /> : <ArrowRight size={16} />}</span>
                <span>{new Date(job.created_at).toLocaleString("fr-FR")}</span>
                <span>{job.status} · {job.progress}%</span>
                {job.error && <span className="warning">{job.error}</span>}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
