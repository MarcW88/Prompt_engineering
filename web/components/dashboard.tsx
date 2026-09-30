"use client";

import { useMemo, useState } from "react";
import {
  Activity, ArrowRight, BarChart3, BookOpen, ChevronDown, CircleHelp,
  Database, FileSearch, FlaskConical, Layers3, Menu, MoreHorizontal, Plus,
  Search, Settings, ShieldCheck, Sparkles, Upload, X,
} from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chartData, promptRecords } from "@/lib/demo-data";
import type { PromptRecord, Provenance } from "@/lib/types";
import { Logo } from "./logo";

const nav = [
  { label: "Vue d'ensemble", icon: BarChart3 },
  { label: "Sources", icon: Database, count: 5 },
  { label: "Questions", icon: CircleHelp, count: 1248 },
  { label: "Clusters", icon: Layers3, count: 86 },
  { label: "Prompts", icon: Sparkles, count: 487 },
  { label: "Analyses", icon: FlaskConical },
];

const steps = [
  { n: "01", title: "Collecter", text: "Questions réelles depuis GSC, Reddit, forums et SERP.", value: "1 248", label: "signaux", icon: Database },
  { n: "02", title: "Structurer", text: "Dédupliquer et regrouper les intentions par proximité.", value: "86", label: "clusters", icon: Layers3 },
  { n: "03", title: "Reconstruire", text: "Inverser les signatures de fan-out en prompts plausibles.", value: "487", label: "prompts", icon: Sparkles },
  { n: "04", title: "Valider", text: "Réexécuter et mesurer la stabilité des réponses.", value: "88%", label: "stabilité", icon: ShieldCheck },
];

const provenanceLabel: Record<Provenance, string> = {
  observed: "Observé",
  reverse_engineered: "Reconstruit",
  synthetic: "Synthétique",
};

export function Dashboard() {
  const [active, setActive] = useState("Vue d'ensemble");
  const [query, setQuery] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const [modal, setModal] = useState(false);
  const [records, setRecords] = useState(promptRecords);
  const filtered = useMemo(() => records.filter((item) => item.prompt.toLowerCase().includes(query.toLowerCase())), [query, records]);

  function addPrompt(prompt: string) {
    const next: PromptRecord = { id: `P-${String(records.length + 25).padStart(3, "0")}`, prompt, provenance: "observed", confidence: 100, status: "draft", engine: "chatgpt", fanOuts: 0, citations: 0, stability: 0 };
    setRecords([next, ...records]);
    setModal(false);
  }

  return (
    <div className="app-shell">
      <aside className={sidebar ? "sidebar open" : "sidebar"}>
        <div className="sidebar-top">
          <Logo />
          <button className="mobile-close" onClick={() => setSidebar(false)} aria-label="Fermer"><X size={18} /></button>
        </div>
        <div className="workspace">
          <span className="workspace-avatar">D</span>
          <div><small>Workspace</small><strong>Decathlon GEO</strong></div>
          <ChevronDown size={16} />
        </div>
        <nav>
          <p>WORKFLOW</p>
          {nav.map(({ label, icon: Icon, count }) => (
            <button key={label} className={active === label ? "active" : ""} onClick={() => { setActive(label); setSidebar(false); }}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>{count && <em>{count.toLocaleString("fr-FR")}</em>}
            </button>
          ))}
          <p>ESPACE</p>
          <button><BookOpen size={18} /><span>Documentation</span></button>
          <button><Settings size={18} /><span>Paramètres</span></button>
        </nav>
        <div className="provider-card">
          <span><Activity size={15} /> Fournisseurs API</span>
          <div><i className="online" /> Bright Data <b>Prêt</b></div>
          <div><i /> Oxylabs <b>À configurer</b></div>
        </div>
        <div className="profile"><span>MW</span><div><strong>Marc Williame</strong><small>Administrateur</small></div><MoreHorizontal size={18} /></div>
      </aside>

      <main>
        <header className="topbar">
          <button className="menu-button" onClick={() => setSidebar(true)} aria-label="Menu"><Menu size={20} /></button>
          <div className="global-search"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher un prompt, un cluster…" /><kbd>⌘ K</kbd></div>
          <button className="help"><CircleHelp size={17} /> Aide</button>
          <button className="primary small" onClick={() => setModal(true)}><Plus size={17} /> Nouveau prompt</button>
        </header>

        <div className="content">
          <section className="hero">
            <div><span className="eyebrow">GEO INTELLIGENCE WORKSPACE</span><h1>Bonjour Marc,</h1><p>Transformez les signaux réels en prompts fiables — puis vérifiez ce que les moteurs génératifs comprennent vraiment.</p></div>
            <button className="primary" onClick={() => setModal(true)}><Plus size={18} /> Lancer une analyse</button>
          </section>

          <section className="metrics">
            <article><div className="metric-icon violet"><CircleHelp /></div><div><span>Questions collectées</span><strong>1 248</strong><small className="up">↑ 12,4% <i>sur 30 jours</i></small></div></article>
            <article><div className="metric-icon blue"><Layers3 /></div><div><span>Intentions détectées</span><strong>86</strong><small>72 exploitables</small></div></article>
            <article><div className="metric-icon amber"><Sparkles /></div><div><span>Prompts reconstruits</span><strong>487</strong><small className="up">392 validés</small></div></article>
            <article><div className="metric-icon green"><ShieldCheck /></div><div><span>Score de stabilité</span><strong>88<span>%</span></strong><small className="up">↑ 4,2 pts</small></div></article>
          </section>

          <section className="workflow-section">
            <div className="section-heading"><div><span className="eyebrow">MÉTHODE</span><h2>Un signal réel, une preuve mesurable</h2></div><button className="text-button">Voir le workflow <ArrowRight size={16} /></button></div>
            <div className="workflow-grid">
              {steps.map(({ n, title, text, value, label, icon: Icon }, index) => (
                <article key={title}>
                  <div className="step-line"><span>{n}</span>{index < steps.length - 1 && <i />}</div>
                  <div className="step-icon"><Icon size={20} /></div><h3>{title}</h3><p>{text}</p><strong>{value}</strong><small>{label}</small>
                </article>
              ))}
            </div>
          </section>

          <section className="split-grid">
            <article className="panel chart-panel">
              <div className="panel-head"><div><span className="eyebrow">ACTIVITÉ</span><h2>Couverture du corpus</h2></div><button className="select-button">7 derniers jours <ChevronDown size={14} /></button></div>
              <div className="chart-legend"><span><i className="dot violet-dot" /> Prompts analysés</span><span><i className="dot green-dot" /> Stabilité moyenne</span></div>
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 8, right: 5, left: -25, bottom: 0 }}>
                    <defs><linearGradient id="violetFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6857db" stopOpacity={0.24}/><stop offset="100%" stopColor="#6857db" stopOpacity={0}/></linearGradient></defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e9e7e2" />
                    <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: "#8b8994", fontSize: 11 }} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8b8994", fontSize: 11 }} />
                    <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e4e1da", boxShadow: "0 8px 24px #322e4420" }} />
                    <Area type="monotone" dataKey="prompts" stroke="#6857db" strokeWidth={2.5} fill="url(#violetFill)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </article>
            <article className="panel source-panel">
              <div className="panel-head"><div><span className="eyebrow">SOURCES</span><h2>Qualité des signaux</h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
              {[
                ["Google Search Console", "542 questions", 94, "G"], ["Reddit & forums", "318 discussions", 86, "R"], ["People Also Ask", "267 questions", 78, "P"], ["Avis clients", "121 signaux", 71, "A"],
              ].map(([name, sub, quality, letter]) => <div className="source-row" key={String(name)}><span className={`source-logo logo-${letter}`}>{letter}</span><div><strong>{name}</strong><small>{sub}</small></div><div className="quality"><span><i style={{ width: `${quality}%` }} /></span><b>{quality}%</b></div></div>)}
              <button className="source-add"><Plus size={16} /> Ajouter une source</button>
            </article>
          </section>

          <section className="panel table-panel">
            <div className="panel-head"><div><span className="eyebrow">PROMPTS RÉCENTS</span><h2>Dernières reconstructions</h2></div><button className="text-button">Voir tous les prompts <ArrowRight size={16} /></button></div>
            <div className="table-scroll"><table><thead><tr><th>Prompt</th><th>Provenance</th><th>Confiance</th><th>Moteur</th><th>Fan-outs</th><th>Stabilité</th><th /></tr></thead><tbody>
              {filtered.map((item) => <tr key={item.id}><td><span className="prompt-id">{item.id}</span><strong>{item.prompt}</strong></td><td><span className={`badge ${item.provenance}`}>{provenanceLabel[item.provenance]}</span></td><td><span className="confidence"><i style={{ width: `${item.confidence}%` }} /></span><b>{item.confidence}%</b></td><td><span className="engine">{item.engine.replaceAll("_", " ")}</span></td><td>{item.fanOuts || "—"}</td><td><span className={item.stability >= 80 ? "score good" : item.stability ? "score medium" : "score"}>{item.stability ? `${item.stability}%` : "—"}</span></td><td><button className="icon-button"><MoreHorizontal size={17} /></button></td></tr>)}
            </tbody></table>{filtered.length === 0 && <div className="empty-state"><FileSearch size={28} /><p>Aucun prompt ne correspond à votre recherche.</p></div>}</div>
          </section>
        </div>
      </main>
      {sidebar && <button className="backdrop" onClick={() => setSidebar(false)} aria-label="Fermer le menu" />}
      {modal && <PromptModal onClose={() => setModal(false)} onSubmit={addPrompt} />}
    </div>
  );
}

function PromptModal({ onClose, onSubmit }: { onClose: () => void; onSubmit: (prompt: string) => void }) {
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("brightdata");
  const [engine, setEngine] = useState("chatgpt");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!prompt.trim()) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, provider, engine, country: "FR", language: "fr" }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Analyse impossible.");
      onSubmit(prompt.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analyse impossible.");
    } finally {
      setLoading(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal" onMouseDown={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); void submit(); }}><div className="modal-head"><div><span className="eyebrow">NOUVELLE OBSERVATION</span><h2>Analyser un prompt</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label>Prompt utilisateur<textarea autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ex. Quelles chaussures de trail choisir pour débuter ?" rows={4} /></label><div className="form-row"><label>Fournisseur<select value={provider} onChange={(e) => setProvider(e.target.value)}><option value="brightdata">Bright Data</option><option value="oxylabs">Oxylabs</option></select></label><label>Moteur<select value={engine} onChange={(e) => setEngine(e.target.value)}><option value="chatgpt">ChatGPT</option><option value="perplexity">Perplexity</option><option value="gemini">Gemini</option><option value="google_ai_mode">Google AI Mode</option></select></label></div>{error && <p className="form-error">{error}</p>}<div className="upload-zone"><Upload size={19} /><span>Ou importer une liste CSV</span></div><div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Annuler</button><button className="primary" disabled={!prompt.trim() || loading}><FlaskConical size={17} /> {loading ? "Analyse…" : "Lancer l'analyse"}</button></div></form></div>;
}
