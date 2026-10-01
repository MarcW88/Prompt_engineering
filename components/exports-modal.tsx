"use client";

import { useEffect, useState } from "react";
import { Download, FileSpreadsheet, X } from "lucide-react";

const exports = [
  { stage: "seeds", title: "Seeds", text: "Mots-clés, thèmes, marques, concurrents et priorités." },
  { stage: "signals", title: "Signaux collectés", text: "Reddit, forums, SERP/PAA, Trustpilot et GSC." },
  { stage: "questions", title: "Questions", text: "Questions observées ou transformées." },
  { stage: "clusters", title: "Clusters", text: "Intentions regroupées et volumes associés." },
  { stage: "dataset", title: "Dataset contrôlé", text: "Exemples, statuts, scores et décisions de revue." },
  { stage: "observations", title: "Observations moteurs", text: "Réponses, moteurs, providers et métadonnées." },
  { stage: "fanouts", title: "Query fan-outs", text: "Requêtes observées via OpenAI web search." },
  { stage: "citations", title: "Citations", text: "URLs, titres et extraits cités par les moteurs." },
  { stage: "validations", title: "Validations", text: "Scores de reproduction, stabilité et qualité." },
  { stage: "prompts", title: "Prompts reconstruits", text: "Prompts observés, synthétiques et reconstruits." },
];

interface DatasetOption { id: string; name: string; status: string }

export function ExportsModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [tier, setTier] = useState(3);

  useEffect(() => {
    if (!projectId) return;
    fetch(`/api/datasets?projectId=${encodeURIComponent(projectId)}`)
      .then((response) => response.ok ? response.json() : { datasets: [] })
      .then((data) => {
        setDatasets(data.datasets ?? []);
        setDatasetId((current) => current || data.datasets?.[0]?.id || "");
      });
  }, [projectId]);

  function url(stage: string, format = "csv") {
    return `/api/exports?projectId=${encodeURIComponent(projectId ?? "")}&stage=${stage}&format=${format}`;
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal docs-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div><span className="eyebrow">EXPORTS</span><h2>Exporter chaque étape</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>
        <p className="export-intro">Chaque livrable peut être exporté en CSV ou JSON. Le CSV convient à Excel/Sheets ; le JSON conserve les données techniques.</p>
        <div className="export-grid">
          {exports.map((item) => (
            <article key={item.stage} className="export-item">
              <div><FileSpreadsheet size={18} /><div><strong>{item.title}</strong><p>{item.text}</p></div></div>
              <span><a className="secondary mini" href={url(item.stage)}>CSV</a><a className="secondary mini" href={url(item.stage, "json")}>JSON</a></span>
            </article>
          ))}
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
