"use client";

import { useEffect, useState } from "react";
import { Download, FileSpreadsheet, X } from "lucide-react";

const exports = [
  { step: "01", phase: "Après saisie des seeds", stage: "seeds", title: "Seeds", text: "Mots-clés, thèmes, marques, concurrents et priorités." },
  { step: "02", phase: "Après collecte", stage: "signals", title: "Signaux bruts", text: "Reddit, forums, SERP/PAA, Trustpilot et GSC." },
  { step: "03", phase: "Après transformation", stage: "questions", title: "Questions", text: "Questions observées ou transformées." },
  { step: "04", phase: "Après clustering", stage: "clusters", title: "Clusters", text: "Intentions regroupées et volumes associés." },
  { step: "05", phase: "Après Dataset Builder", stage: "dataset", title: "Dataset contrôlé", text: "Exemples, statuts, scores et décisions de revue." },
  { step: "05", phase: "Après exécution", stage: "observations", title: "Réponses moteurs", text: "Réponses, moteurs, providers et métadonnées." },
  { step: "05", phase: "Après exécution", stage: "fanouts", title: "Query fan-outs", text: "Requêtes observées via OpenAI web search." },
  { step: "05", phase: "Après exécution", stage: "citations", title: "Citations", text: "URLs, titres et extraits cités par les moteurs." },
  { step: "06", phase: "Après validation", stage: "validations", title: "Validations", text: "Scores de reproduction, stabilité et qualité." },
  { step: "07", phase: "Après reverse engineering", stage: "prompts", title: "Prompts reconstruits", text: "Prompts observés, synthétiques et reconstruits." },
  { step: "08", phase: "Après revue manuelle", stage: "approved", title: "Prompts approuvés", text: "Prompts acceptés et approuvés pour l’export Semactic." },
];

const emptyReasons: Record<string, string> = {
  seeds: "Renseigne des seeds et lance une collecte.",
  signals: "Lance d’abord une collecte de sources.",
  questions: "Transforme les signaux en questions via le workflow.",
  clusters: "Lance le clustering depuis le workflow.",
  dataset: "Construis un dataset avec le Dataset Builder.",
  observations: "Le Dataset Builder n’a pas encore produit d’observations. Vérifie que le job s’est terminé sans erreur.",
  fanouts: "Aucune observation avec fan-outs. Attends que les exécutions moteur se terminent.",
  citations: "Aucune observation avec citations. Dépend du moteur utilisé.",
  validations: "Valide les prompts acceptés sur 3 runs.",
  prompts: "Lance le reverse engineering après validation.",
  approved: "Approuve des prompts dans la revue manuelle.",
};

interface DatasetOption { id: string; name: string; status: string }

export function ExportsModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [tier, setTier] = useState(3);
  const [counts, setCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!projectId) return;
    fetch(`/api/datasets?projectId=${encodeURIComponent(projectId)}`)
      .then((response) => response.ok ? response.json() : { datasets: [] })
      .then((data) => {
        setDatasets(data.datasets ?? []);
        setDatasetId((current) => current || data.datasets?.[0]?.id || "");
      });
    fetch(`/api/exports?projectId=${encodeURIComponent(projectId)}&stage=summary&format=json`)
      .then((response) => response.ok ? response.json() : { counts: {} })
      .then((data) => setCounts(data.counts ?? {}));
  }, [projectId]);

  function url(stage: string, format = "csv") {
    return `/api/exports?projectId=${encodeURIComponent(projectId ?? "")}&stage=${stage}&format=${format}`;
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal exports-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div><span className="eyebrow">EXPORTS</span><h2>Exporter chaque étape</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="export-intro">Chaque ligne correspond au moment du workflow où l’export devient utile. CSV et XLSX s’ouvrent dans Excel/Sheets ; JSON conserve les données techniques.</p>
        <div className="export-grid">
          {exports.map((item) => {
            const count = counts[item.stage] ?? 0;
            const ready = count > 0;
            return (
              <article key={item.stage} className={ready ? "export-item ready" : "export-item pending"}>
                <div><FileSpreadsheet size={18} /><div><span className="export-step">Étape {item.step} · {item.phase}</span><strong>{item.title}</strong><p>{item.text}</p><em className={ready ? "export-status ready" : "export-status"}>{ready ? `Disponible · ${count.toLocaleString("fr-FR")} ligne${count > 1 ? "s" : ""}` : `${emptyReasons[item.stage] ?? "Aucune donnée"}`}</em></div></div>
                <span>{["csv", "xlsx", "json"].map((format) => ready ? <a key={format} className="secondary mini" href={url(item.stage, format)}>{format === "xlsx" ? "Excel" : format.toUpperCase()}</a> : <i key={format} className="secondary mini export-disabled">{format === "xlsx" ? "Excel" : format.toUpperCase()}</i>)}</span>
              </article>
            );
          })}
        </div>
        <div className="semactic-export">
          <div>
            <span className="eyebrow">EXPORT FINAL</span>
            <h3>Semactic — prompts approuvés uniquement</h3>
          </div>
          <div className="form-row">
            <label>Dataset<select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.status}</option>)}</select></label>
            <label>Tier<select value={tier} onChange={(event) => setTier(Number(event.target.value))}><option value={1}>Tier 1</option><option value={2}>Tier ≤ 2</option><option value={3}>Tier ≤ 3</option></select></label>
          </div>
          <a className={datasetId ? "primary export-final" : "primary export-final disabled"} href={datasetId ? `/api/datasets/export?datasetId=${encodeURIComponent(datasetId)}&tier=${tier}` : "#"}><Download size={16} /> Télécharger le CSV Semactic</a>
        </div>
      </section>
    </div>
  );
}
