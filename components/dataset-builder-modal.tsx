"use client";

import { useMemo, useState } from "react";
import { Database, Download, X } from "lucide-react";
import { estimateDatasetExecutions } from "@/lib/data/datasets";

const engineLabels: Record<string, string> = {
  chatgpt: "ChatGPT",
  perplexity: "Perplexity",
  gemini: "Gemini",
  google_ai_mode: "Google AI Mode",
};

export function DatasetBuilderModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [name, setName] = useState("Dataset GEO initial");
  const [candidatePoolSize, setCandidatePoolSize] = useState(50);
  const [executionSampleSize, setExecutionSampleSize] = useState(5);
  const [repetitions, setRepetitions] = useState(1);
  const [candidatesPerCluster, setCandidatesPerCluster] = useState(3);
  const [engines, setEngines] = useState(["chatgpt"]);
  const [qualityThreshold, setQualityThreshold] = useState(0.55);
  const [costPerExecutionEur, setCostPerExecutionEur] = useState(0.02);
  const [maxBudgetEur, setMaxBudgetEur] = useState(1);
  const [datasetId, setDatasetId] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const executions = useMemo(() => estimateDatasetExecutions({ executionSampleSize, repetitions, engines }), [executionSampleSize, repetitions, engines]);
  const estimatedCost = executions * costPerExecutionEur;
  const highCost = estimatedCost >= 10;
  const waves = Math.ceil(executions / 5);
  const minMinutes = waves * 5;
  const maxMinutes = waves * 15;
  const realism = executions <= 5
    ? { label: "Micro-test recommandé", tone: "good", text: "Idéal pour vérifier le workflow et les exports sans attendre trop longtemps." }
    : executions <= 20
      ? { label: "Test réaliste", tone: "medium", text: "Suffisant pour évaluer la diversité des clusters, mais Bright Data peut prendre 20 à 60 minutes." }
      : executions <= 100
        ? { label: "Analyse large", tone: "warn", text: "À réserver après un premier test réussi. Vérifiez le budget et laissez le job tourner en arrière-plan." }
        : { label: "Analyse massive", tone: "warn", text: "Non recommandée pour un test. Réduisez l'échantillon ou augmentez progressivement." };

  function plannedBudget(nextExecutions: number, nextCost = costPerExecutionEur) {
    return Math.max(1, Math.ceil(nextExecutions * nextCost * 1.25));
  }

  function updateCandidatePool(value: number) {
    const corpus = Math.max(1, value || 1);
    const recommendedSample = Math.min(corpus, Math.max(1, Math.min(50, Math.ceil(corpus * 0.1))));
    const recommendedCandidates = Math.max(1, Math.min(9, Math.ceil(corpus / 20)));
    setCandidatePoolSize(corpus);
    setExecutionSampleSize(recommendedSample);
    setCandidatesPerCluster(recommendedCandidates);
    setMaxBudgetEur(plannedBudget(recommendedSample * repetitions * engines.length));
  }

  function updateExecutionSample(value: number) {
    const sample = Math.max(1, Math.min(candidatePoolSize, value || 1));
    setExecutionSampleSize(sample);
    setMaxBudgetEur(plannedBudget(sample * repetitions * engines.length));
  }

  function updateCostPerExecution(value: number) {
    const cost = Math.max(0, value || 0);
    setCostPerExecutionEur(cost);
    setMaxBudgetEur(plannedBudget(executions, cost));
  }

  function toggleEngine(engine: string) {
    const nextEngines = engines.includes(engine) ? engines.filter((item) => item !== engine) : [...engines, engine];
    setEngines(nextEngines);
    setMaxBudgetEur(plannedBudget(executionSampleSize * repetitions * nextEngines.length));
  }

  async function submit() {
    if (!projectId) { setStatus("Créez d'abord un workspace Supabase."); return; }
    if (highCost && !window.confirm(`Coût estimé : ${estimatedCost.toFixed(2)} €. Cette analyse dépasse 10 €. Confirmer le lancement ?`)) return;
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

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal dataset-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <div className="modal-head">
          <div><span className="eyebrow">REVERSE ENGINEERING</span><h2>Dataset Builder</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>

        <div className="builder-guide">
          <strong>Comment lire ce formulaire</strong>
          <ol>
            <li>Le corpus candidat prépare les prompts possibles à partir des clusters.</li>
            <li>L&rsquo;échantillon exécuté est le nombre de prompts réellement envoyés aux moteurs.</li>
            <li>Chaque moteur coché multiplie le nombre d&rsquo;exécutions payantes.</li>
            <li>La validation à 3 runs se fait ensuite seulement sur les prompts acceptés.</li>
          </ol>
        </div>

        <label>Nom du dataset<input value={name} onChange={(event) => setName(event.target.value)} /></label>

        <div className="form-row">
          <label>Corpus candidat<input type="number" min="1" max="20000" value={candidatePoolSize} onChange={(event) => updateCandidatePool(Number(event.target.value))} /><small>Volume total de variantes à préparer. Ne correspond pas encore à des appels payants.</small></label>
          <label>Échantillon exécuté<input type="number" min="1" max={candidatePoolSize} value={executionSampleSize} onChange={(event) => updateExecutionSample(Number(event.target.value))} /><small>Nombre de prompts réellement envoyés. Pour un premier test : 5.</small></label>
        </div>
        <div className="form-row">
          <label>Candidats par cluster<input type="number" min="1" max="36" value={candidatesPerCluster} onChange={(event) => setCandidatesPerCluster(Number(event.target.value))} /><small>Diversité maximale par intention. 3 suffit pour un test.</small></label>
          <label>Runs de screening<input type="number" min="1" max="1" value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} /><small>Premier passage uniquement ; la stabilité complète se mesure ensuite à 3 ou 5 runs.</small></label>
        </div>
        <div className="form-row">
          <label>Coût estimé par appel (€)<input type="number" min="0" step="0.001" value={costPerExecutionEur} onChange={(event) => updateCostPerExecution(Number(event.target.value))} /><small>Sert uniquement au plafond. Le coût réel reste visible dans “Coûts réels”.</small></label>
          <label>Budget maximum (€)<input type="number" min="0" step="1" value={maxBudgetEur} onChange={(event) => setMaxBudgetEur(Number(event.target.value))} /><small>Plafond de sécurité du job. Le worker s&rsquo;arrête avant de le dépasser.</small></label>
        </div>
        <div className="form-row">
          <label>Seuil qualité<input type="number" min="0" max="1" step="0.05" value={qualityThreshold} onChange={(event) => setQualityThreshold(Number(event.target.value))} /><small>0,55 est un bon point de départ. Plus bas accepte plus de prompts ; plus haut est plus strict.</small></label>
        </div>

        <fieldset>
          <legend>Moteurs d&rsquo;exécution</legend>
          {Object.entries(engineLabels).map(([engine, label]) => (
            <label className="check-option" key={engine}>
              <input type="checkbox" checked={engines.includes(engine)} onChange={() => toggleEngine(engine)} /> {label}
            </label>
          ))}
          <small>Commencez par ChatGPT seul. Ajouter Perplexity ou Gemini multiplie les appels et la durée.</small>
        </fieldset>

        <div className={`dataset-estimate ${highCost ? "warn" : realism.tone}`}>
          <div><strong>{executions.toLocaleString("fr-FR")}</strong><span>observations prévues</span></div>
          <p>{candidatePoolSize.toLocaleString("fr-FR")} candidats → {executionSampleSize.toLocaleString("fr-FR")} exécutés · coût estimé {estimatedCost.toFixed(2)} € / plafond {maxBudgetEur.toFixed(2)} €</p>
          <p>{realism.label} — {realism.text}</p>
          <p>Durée indicative : environ {minMinutes} à {maxMinutes} minutes, selon la latence Bright Data. {estimatedCost > maxBudgetEur ? "Le plafond peut limiter la fin du job." : ""}</p>
          {highCost && <p className="cost-alert"><strong>Alerte budget :</strong> l’estimation dépasse 10 €. Le lancement demandera une confirmation explicite.</p>}
        </div>

        {status && <p className="import-status">{status}</p>}
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose}>Fermer</button>
          {datasetId && <button type="button" className="secondary" onClick={() => void validate(3)}>Valider à 3 runs</button>}
          {datasetId && <a className="secondary" href={`/api/datasets/export?datasetId=${encodeURIComponent(datasetId)}&tier=3`}><Download size={16} /> Export approuvé</a>}
          <button className="primary" disabled={loading || !engines.length}><Database size={17} /> {loading ? "Préparation…" : "Construire & échantillonner"}</button>
        </div>
      </form>
    </div>
  );
}
