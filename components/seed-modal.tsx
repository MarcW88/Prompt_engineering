"use client";

import { useState } from "react";
import { Database, Play, X } from "lucide-react";
import { parseSeedText, type SeedType } from "@/lib/data/seeds";

export function SeedModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [text, setText] = useState("");
  const [seedType, setSeedType] = useState<SeedType>("keyword");
  const [priority, setPriority] = useState(70);
  const [sources, setSources] = useState(["reddit", "forum", "serp", "review"]);
  const [queryBudget, setQueryBudget] = useState(10);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  function toggleSource(source: string) {
    setSources((current) => current.includes(source) ? current.filter((item) => item !== source) : [...current, source]);
  }

  async function submit() {
    if (!projectId) { setStatus("Créez et connectez d'abord un workspace Supabase."); return; }
    const seeds = parseSeedText(text, { seedType, priority, source: "dashboard" });
    if (!seeds.length) { setStatus("Ajoutez au moins un mot-clé."); return; }
    setLoading(true);
    setStatus("Enregistrement des seeds…");
    try {
      const seedResponse = await fetch("/api/seeds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, seeds }) });
      const seedData = await seedResponse.json();
      if (!seedResponse.ok) throw new Error(seedData.error ?? "Import impossible.");
      setStatus("Création du job de collecte…");
      const jobResponse = await fetch("/api/jobs/collect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, sources, queryBudget }) });
      const jobData = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(jobData.error ?? "Job impossible.");
      setStatus(`${seeds.length} seeds enregistrés. Collecte mise en file pour ${sources.join(", ")}.`);
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Opération impossible.");
    } finally {
      setLoading(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal seed-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void submit(); }}><div className="modal-head"><div><span className="eyebrow">SEEDS DE COLLECTE</span><h2>Ajouter des mots-clés</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label>Mots-clés, un par ligne<textarea autoFocus rows={7} value={text} onChange={(event) => setText(event.target.value)} placeholder={"chaussures trail débutant\nveste randonnée imperméable\nmal au genou après running"} /></label><div className="form-row"><label>Type<select value={seedType} onChange={(event) => setSeedType(event.target.value as SeedType)}><option value="keyword">Mot-clé</option><option value="theme">Thème</option><option value="brand">Marque</option><option value="competitor">Concurrent</option><option value="product">Produit</option><option value="problem">Problème</option></select></label><label>Priorité<input type="number" min="0" max="100" value={priority} onChange={(event) => setPriority(Number(event.target.value))} /></label></div><div className="form-row"><label>Budget max de requêtes par source<input type="number" min="1" max="200" value={queryBudget} onChange={(event) => setQueryBudget(Number(event.target.value))} /></label></div><fieldset><legend>Sources à interroger</legend>{["reddit", "forum", "serp", "review"].map((source) => <label className="check-option" key={source}><input type="checkbox" checked={sources.includes(source)} onChange={() => toggleSource(source)} /> {source === "serp" ? "PAA & suggestions" : source === "review" ? "Trustpilot & avis" : source}</label>)}</fieldset>{status && <p className="import-status">{status}</p>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Fermer</button><button className="primary" disabled={loading || !text.trim() || !sources.length}><Database size={17} />{loading ? "Préparation…" : "Enregistrer & collecter"}<Play size={14} /></button></div></form></div>;
}
