"use client";

import { useMemo, useState } from "react";
import { Database, X } from "lucide-react";
import { estimateDatasetExecutions } from "@/lib/data/datasets";

export function DatasetBuilderModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [name, setName] = useState("Dataset GEO initial");
  const [targetSize, setTargetSize] = useState(600);
  const [repetitions, setRepetitions] = useState(3);
  const [candidatesPerCluster, setCandidatesPerCluster] = useState(9);
  const [engines, setEngines] = useState(["chatgpt"]);
  const [qualityThreshold, setQualityThreshold] = useState(0.65);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const executions = useMemo(() => estimateDatasetExecutions({ targetSize, repetitions, engines }), [targetSize, repetitions, engines]);

  function toggleEngine(engine: string) {
    setEngines((current) => current.includes(engine) ? current.filter((item) => item !== engine) : [...current, engine]);
  }

  async function submit() {
    if (!projectId) { setStatus("Créez d'abord un workspace Supabase."); return; }
    setLoading(true);
    setStatus("Création du dataset…");
    try {
      const response = await fetch("/api/datasets/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, name, targetSize, repetitions, candidatesPerCluster, engines, qualityThreshold, stages: ["discovery", "comparison"], specificityLevels: [0, 1, 2] }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Construction impossible.");
      setStatus(`Dataset créé. ${executions.toLocaleString("fr-FR")} exécutions planifiées dans le worker.`);
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Construction impossible.");
    } finally {
      setLoading(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal dataset-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void submit(); }}><div className="modal-head"><div><span className="eyebrow">REVERSE ENGINEERING</span><h2>Dataset Builder</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label>Nom du dataset<input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="form-row"><label>Prompts candidats<input type="number" min="1" max="20000" value={targetSize} onChange={(event) => setTargetSize(Number(event.target.value))} /></label><label>Répétitions par moteur<input type="number" min="1" max="10" value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} /></label></div><div className="form-row"><label>Candidats par cluster<input type="number" min="1" max="36" value={candidatesPerCluster} onChange={(event) => setCandidatesPerCluster(Number(event.target.value))} /></label><label>Seuil qualité<input type="number" min="0" max="1" step="0.05" value={qualityThreshold} onChange={(event) => setQualityThreshold(Number(event.target.value))} /></label></div><fieldset><legend>Moteurs d&apos;exécution</legend>{["chatgpt", "perplexity", "gemini", "google_ai_mode"].map((engine) => <label className="check-option" key={engine}><input type="checkbox" checked={engines.includes(engine)} onChange={() => toggleEngine(engine)} /> {engine.replaceAll("_", " ")}</label>)}</fieldset><div className="execution-estimate"><strong>{executions.toLocaleString("fr-FR")}</strong><span>observations prévues</span><small>{targetSize.toLocaleString("fr-FR")} prompts × {repetitions} répétitions × {engines.length} moteur{engines.length > 1 ? "s" : ""}</small></div>{status && <p className="import-status">{status}</p>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Fermer</button><button className="primary" disabled={loading || !name.trim() || !engines.length}><Database size={17} />{loading ? "Construction…" : "Construire le dataset"}</button></div></form></div>;
}
