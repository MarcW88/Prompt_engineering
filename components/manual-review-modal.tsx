"use client";

import { useEffect, useState } from "react";
import { Check, Download, Pencil, X } from "lucide-react";

type Dataset = { id: string; name: string; status: string };
type ReviewExample = {
  id: string;
  manual_review_status: "pending" | "approved" | "rejected";
  review_note: string | null;
  edited_prompt_text: string | null;
  quality_score: number | null;
  stability_score: number | null;
  reproduction_score: number | null;
  persona: string | null;
  journey_stage: string | null;
  prompts: { text: string; provenance: string; clusters: { label: string } | null };
};

export function ManualReviewModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [examples, setExamples] = useState<ReviewExample[]>([]);
  const [index, setIndex] = useState(0);
  const [editedText, setEditedText] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!projectId) return;
    fetch(`/api/datasets?projectId=${encodeURIComponent(projectId)}`).then((response) => response.json()).then((data) => {
      const values = data.datasets ?? [];
      setDatasets(values);
      if (values[0]) setDatasetId(values[0].id);
    });
  }, [projectId]);

  useEffect(() => {
    if (!datasetId) return;
    fetch(`/api/datasets/review?datasetId=${encodeURIComponent(datasetId)}`).then((response) => response.json()).then((data) => {
      const values = data.examples ?? [];
      setExamples(values);
      setIndex(0);
      setEditedText(values[0]?.edited_prompt_text || values[0]?.prompts.text || "");
      setNote(values[0]?.review_note || "");
    });
  }, [datasetId]);

  const example = examples[index];

  function selectIndex(nextIndex: number) {
    const bounded = Math.max(0, Math.min(examples.length - 1, nextIndex));
    const next = examples[bounded];
    setIndex(bounded);
    setEditedText(next?.edited_prompt_text || next?.prompts.text || "");
    setNote(next?.review_note || "");
  }

  async function decide(status: "approved" | "rejected") {
    if (!example) return;
    const response = await fetch("/api/datasets/review", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exampleId: example.id, status, note, editedPromptText: editedText }) });
    if (!response.ok) { const data = await response.json(); setMessage(data.error ?? "Mise à jour impossible."); return; }
    setExamples((current) => current.map((item) => item.id === example.id ? { ...item, manual_review_status: status, review_note: note, edited_prompt_text: editedText } : item));
    setMessage(status === "approved" ? "Prompt approuvé." : "Prompt rejeté.");
    if (index < examples.length - 1) selectIndex(index + 1);
  }

  const approved = examples.filter((item) => item.manual_review_status === "approved").length;
  return <div className="modal-backdrop" onMouseDown={onClose}><div className="modal review-modal" onMouseDown={(event) => event.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">VALIDATION HUMAINE</span><h2>Revue des prompts</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label>Dataset<select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.status}</option>)}</select></label>{example ? <div className="review-card"><div className="review-progress"><span>{index + 1} / {examples.length}</span><span>{approved} approuvés</span></div><div className="review-meta"><span>{example.prompts.clusters?.label ?? "Sans cluster"}</span><span>{example.persona ?? "Persona non défini"}</span><span>{example.journey_stage ?? "Intention non définie"}</span></div><label>Prompt éditable<textarea rows={5} value={editedText} onChange={(event) => setEditedText(event.target.value)} /></label><div className="review-scores"><span>Qualité <b>{Math.round(Number(example.quality_score ?? 0) * 100)}%</b></span><span>Stabilité <b>{Math.round(Number(example.stability_score ?? 0) * 100)}%</b></span><span>Reproduction <b>{Math.round(Number(example.reproduction_score ?? 0) * 100)}%</b></span></div><label>Note interne<textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Pourquoi garder, modifier ou rejeter ce prompt ?" /></label><div className="review-actions"><button className="secondary reject" onClick={() => void decide("rejected")}><X size={16} /> Rejeter</button><button className="secondary" onClick={() => setEditedText(example.prompts.text)}><Pencil size={15} /> Réinitialiser</button><button className="primary" onClick={() => void decide("approved")}><Check size={16} /> Approuver</button></div></div> : <div className="empty-state"><p>Aucun prompt accepté à revoir dans ce dataset.</p></div>}{message && <p className="import-status">{message}</p>}<div className="modal-actions"><button className="secondary" onClick={() => selectIndex(index - 1)} disabled={index === 0}>Précédent</button><button className="secondary" onClick={() => selectIndex(index + 1)} disabled={!example || index >= examples.length - 1}>Suivant</button>{datasetId && <a className="primary" href={`/api/datasets/export?datasetId=${encodeURIComponent(datasetId)}&tier=3`}><Download size={15} /> Export approuvés</a>}</div></div></div>;
}
