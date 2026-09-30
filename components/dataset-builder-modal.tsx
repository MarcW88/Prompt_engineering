"use client";

import { useMemo, useState } from "react";
import { Database, Download, X } from "lucide-react";
import { estimateDatasetExecutions } from "@/lib/data/datasets";

export function DatasetBuilderModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [name, setName] = useState("Dataset GEO initial");
  const [candidatePoolSize, setCandidatePoolSize] = useState(2000);
  const [executionSampleSize, setExecutionSampleSize] = useState(100);
  const [repetitions, setRepetitions] = useState(1);
  const [candidatesPerCluster, setCandidatesPerCluster] = useState(9);
  const [engines, setEngines] = useState(["chatgpt"]);
  const [qualityThreshold, setQualityThreshold] = useState(0.65);
  const [costPerExecutionEur, setCostPerExecutionEur] = useState(0.02);
  const [maxBudgetEur, setMaxBudgetEur] = useState(20);
  const [datasetId, setDatasetId] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const executions = useMemo(() => estimateDatasetExecutions({ executionSampleSize, repetitions, engines }), [executionSampleSize, repetitions, engines]);
  const estimatedCost = executions * costPerExecutionEur;

  function toggleEngine(engine: string) {
    setEngines((current) => current.includes(engine) ? current.filter((item) => item !== engine) : [...current, engine]);
  }

  async function submit() {
    if (!projectId) { setStatus("Créez d'abord un workspace Supabase."); return; }
    setLoading(true);
    setStatus("Création du corpus candidat…");
    try {
      const response = await fetch("/api/datasets/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, name, candidatePoolSize, executionSampleSize, repetitions, candidatesPerCluster, engines, qualityThreshold, costPerExecutionEur, maxBudgetEur, stages: ["discovery", "comparison"], specificityLevels: [0, 1, 2] }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Construction impossible.");
      setDatasetId(data.dataset.id);
      setStatus(`${candidatePoolSize.toLocaleString("fr-FR")} candidats à construire, ${executions.toLocaleString("fr-FR")} observations de screening planifiées.`);
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Construction impossible.");
    } finally {
      setLoading(false);
    }
  }

  async function validate(targetRuns: 3 | 5) {
    if (!projectId || !datasetId) return;
    setStatus(`Planification de la vague à ${targetRuns} runs…`);
    const response = await fetch("/api/datasets/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, datasetId, targetRuns, limit: targetRuns === 3 ? 100 : 50 }) });
    const data = await response.json();
    setStatus(response.ok ? `Vague ${targetRuns} runs ajoutée à la file du worker.` : data.error ?? "Planification impossible.");
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal dataset-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void submit(); }}><div className="modal-head"><div><span className="eyebrow">REVERSE ENGINEERING</span><h2>Dataset Builder</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label>Nom du dataset<input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="form-row"><label>Corpus candidat<input type="number" min="1" max="20000" value={candidatePoolSize} onChange={(event) => setCandidatePoolSize(Number(event.target.value))} /></label><label>Échantillon exécuté<input type="number" min="1" max={candidatePoolSize} value={executionSampleSize} onChange={(event) => setExecutionSampleSize(Number(event.target.value))} /></label></div><div className="form-row"><label>Candidats par cluster<input type="number" min="1" max="36" value={candidatesPerCluster} onChange={(event) => setCandidatesPerCluster(Number(event.target.value))} /></label><label>Runs de screening<input type="number" min="1" max="1" value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} /></label></div><div className="form-row"><label>Coût estimé par appel (€)<input type="number" min="0" step="0.001" value={costPerExecutionEur} onChange={(event) => setCostPerExecutionEur(Number(event.target.value))} /></label><label>Budget maximum (€)<input type="number" min="0" step="1" value={maxBudgetEur} onChange={(event) => setMaxBudgetEur(Number(event.target.value))} /></label></div><div className="form-row"><label>Seuil qualité<input type="number" min="0" max="1" step="0.05" value={qualityThreshold} onChange={(event) => setQualityThreshold(Number(event.target.value))} /></label></div><fieldset><legend>Moteurs d&apos;exécution</legend>{["chatgpt", "perplexity", "gemini", "google_ai_mode"].map((engine) => <label className="check-option" key={engine}><input type="checkbox" checked={engines.includes(engine)} onChange={() => toggleEngine(engine)} /> {engine.replaceAll("_", " ")}</label>)}</fieldset><div className="execution-estimate"><strong>{executions.toLocaleString("fr-FR")}</strong><span>observations prévues</span><small>{candidatePoolSize.toLocaleString("fr-FR")} candidats → {executionSampleSize.toLocaleString("fr-FR")} exécutés · coût estimé {estimatedCost.toFixed(2)} € / plafond {maxBudgetEur.toFixed(2)} €</small></div>{status && <p className="import-status">{status}</p>}{datasetId && <div className="wave-actions"><button type="button" className="secondary" onClick={() => void validate(3)}>Valider 100 prompts × 3 runs</button><button type="button" className="secondary" onClick={() => void validate(5)}>Tier 1 : 50 × 5 runs</button><a className="secondary" href={`/api/datasets/export?datasetId=${encodeURIComponent(datasetId)}&tier=3`}><Download size={15} /> Export Semactic</a></div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Fermer</button><button className="primary" disabled={loading || !name.trim() || !engines.length || estimatedCost > maxBudgetEur}><Database size={17} />{loading ? "Construction…" : "Construire & échantillonner"}</button></div></form></div>;
}
