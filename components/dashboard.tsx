"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowRight, BarChart3, BookOpen, ChevronDown, CircleDollarSign, CircleHelp,
  Database, Download, FileSearch, FlaskConical, Layers3, Menu, MoreHorizontal, Plus,
  Search, Settings, ShieldCheck, Sparkles, X,
} from "lucide-react";

import type { PromptRecord, Provenance } from "@/lib/types";
import { Logo } from "./logo";
import { SeedModal } from "./seed-modal";
import { DatasetBuilderModal } from "./dataset-builder-modal";
import { PipelineModal } from "./pipeline-modal";
import { ManualReviewModal } from "./manual-review-modal";
import { CostsModal } from "./costs-modal";
import { DocumentationModal } from "./documentation-modal";
import { ExecutionCenterModal } from "./execution-center-modal";
import { ExportsModal } from "./exports-modal";
import { WorkspaceModal } from "./workspace-modal";

const nav = [
  { label: "Vue d'ensemble", icon: BarChart3 },
  { label: "Sources", icon: Database },
  { label: "Questions", icon: CircleHelp },
  { label: "Clusters", icon: Layers3 },
  { label: "Prompts", icon: Sparkles },
  { label: "Analyses", icon: FlaskConical },
];

const steps = [
  { n: "01", title: "Collecter", text: "Questions réelles depuis GSC, Reddit, forums, avis et SERP.", value: "1 248", label: "signaux", icon: Database },
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
  const [seedModal, setSeedModal] = useState(false);
  const [datasetModal, setDatasetModal] = useState(false);
  const [pipelineModal, setPipelineModal] = useState(false);
  const [reviewModal, setReviewModal] = useState(false);
  const [costsModal, setCostsModal] = useState(false);
  const [docsModal, setDocsModal] = useState(false);
  const [executionModal, setExecutionModal] = useState(false);
  const [exportsModal, setExportsModal] = useState(false);
  const [workspaceModal, setWorkspaceModal] = useState(false);
  const [records, setRecords] = useState<PromptRecord[]>([]);
  const [metrics, setMetrics] = useState({ questions: 0, clusters: 0, prompts: 0, stability: 0 });
  const [sources, setSources] = useState<Array<{ id: string; name: string; kind: string; enabled: boolean }>>([]);
  const [configured, setConfigured] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("Workspace GEO");
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const filtered = useMemo(() => records.filter((item) => item.prompt.toLowerCase().includes(query.toLowerCase())), [query, records]);

  async function loadDashboard(selectedProjectId?: string) {
    const suffix = selectedProjectId ? `?projectId=${encodeURIComponent(selectedProjectId)}` : "";
    const response = await fetch(`/api/dashboard${suffix}`);
    if (!response.ok) throw new Error("Dashboard indisponible");
    const data = await response.json();
    setConfigured(Boolean(data.configured));
    setProjectId(data.projectId ?? null);
    setProjectName(data.projectName ?? "Workspace GEO");
    setMetrics(data.metrics);
    setSources(data.sources);
    setRecords(data.prompts.map((item: { id: string; text: string; provenance: Provenance; confidence: number; status: PromptRecord["status"] }) => ({
      id: item.id.slice(0, 8), prompt: item.text, provenance: item.provenance, confidence: Math.round(Number(item.confidence) * 100), status: item.status,
      engine: "chatgpt", fanOuts: 0, citations: 0, stability: 0,
    })));
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDashboard().catch(() => {
        setConfigured(false);
        setRecords([]);
      });
    }, 0);
    fetch("/api/projects").then((response) => response.ok ? response.json() : null).then((data) => {
      setProjects(data?.projects?.map((item: { id: string; name: string }) => ({ id: item.id, name: item.name })) ?? []);
    }).catch(() => setProjects([]));
    return () => window.clearTimeout(timer);
  }, []);

  const workflowValues = [metrics.questions, metrics.clusters, metrics.prompts, `${metrics.stability}%`];

  async function switchWorkspace(id: string) {
    await loadDashboard(id).catch(() => setRecords([]));
  }

  async function workspaceCreated(project: { id: string; name: string }) {
    setProjects((current) => [...current, project]);
    setWorkspaceModal(false);
    await switchWorkspace(project.id);
  }

  function reloadAfterPromptTest() {
    setModal(false);
    window.location.reload();
  }

  return (
    <div className="app-shell">
      <aside className={sidebar ? "sidebar open" : "sidebar"}>
        <div className="sidebar-top">
          <Logo />
          <button className="mobile-close" onClick={() => setSidebar(false)} aria-label="Fermer"><X size={18} /></button>
        </div>
        <div className="workspace">
          <span className="workspace-avatar">{projectName.slice(0, 1).toUpperCase()}</span>
          <div><small>Workspace</small>{projects.length > 1 ? <select className="workspace-select" value={projectId ?? ""} onChange={(event) => void switchWorkspace(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select> : <strong>{projectName}</strong>}</div>
          <button type="button" className="workspace-add" onClick={() => setWorkspaceModal(true)} aria-label="Créer un workspace"><Plus size={15} /></button>
        </div>
        <nav>
          <p>WORKFLOW</p>
          {nav.map(({ label, icon: Icon }) => (
            <button key={label} className={active === label ? "active" : ""} onClick={() => { setActive(label); setSidebar(false); }}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
            </button>
          ))}
          <p>ESPACE</p>
          <button onClick={() => setDocsModal(true)}><BookOpen size={18} /><span>Documentation</span></button>
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
          <button className="help" onClick={() => setDocsModal(true)}><CircleHelp size={17} /> Aide</button>
          <button className="secondary small" onClick={() => setExecutionModal(true)}><Activity size={16} /> Progression</button>
          <button className="secondary small" onClick={() => setExportsModal(true)}><Download size={16} /> Exports</button>
          <button className="secondary small" onClick={() => setModal(true)}><FlaskConical size={17} /> Tester un prompt</button>
          <button className="primary small" onClick={() => setSeedModal(true)}><Plus size={17} /> Nouvelle collecte</button>
        </header>

        <div className="content">
          <section className="hero">
            <div><span className="eyebrow">GEO INTELLIGENCE WORKSPACE</span><h1>Bonjour Marc,</h1><p>Transformez les signaux réels en prompts fiables — puis vérifiez ce que les moteurs génératifs comprennent vraiment.</p></div>
            <div className="hero-actions"><button className="secondary" onClick={() => setCostsModal(true)}><CircleDollarSign size={17} /> Coûts réels</button><button className="secondary" onClick={() => setReviewModal(true)}><ShieldCheck size={17} /> Revue manuelle</button><button className="secondary" onClick={() => setDatasetModal(true)}><Database size={17} /> Dataset Builder</button></div>
          </section>

          {!configured && <div className="setup-banner"><Database size={17} /><div><strong>Base de données à connecter</strong><span>Ajoutez NEXT_PUBLIC_SUPABASE_URL et SUPABASE_SECRET_KEY dans Vercel pour activer les données réelles.</span></div></div>}
          {configured && !projectId && <div className="setup-banner"><Database size={17} /><div><strong>Créez votre premier workspace</strong><span>Le projet regroupera les sources, questions, prompts et observations.</span></div><button className="secondary" onClick={() => setWorkspaceModal(true)}>Créer un workspace</button></div>}
          <section className="metrics">
            <article><div className="metric-icon violet"><CircleHelp /></div><div><span>Questions collectées</span><strong>{metrics.questions.toLocaleString("fr-FR")}</strong><small>Données persistées</small></div></article>
            <article><div className="metric-icon blue"><Layers3 /></div><div><span>Intentions détectées</span><strong>{metrics.clusters.toLocaleString("fr-FR")}</strong><small>Clusters disponibles</small></div></article>
            <article><div className="metric-icon amber"><Sparkles /></div><div><span>Prompts reconstruits</span><strong>{metrics.prompts.toLocaleString("fr-FR")}</strong><small>Corpus actif</small></div></article>
            <article><div className="metric-icon green"><ShieldCheck /></div><div><span>Score de stabilité</span><strong>{metrics.stability}<span>%</span></strong><small>Moyenne des validations</small></div></article>
          </section>

          <section className="workflow-section">
            <div className="section-heading"><div><span className="eyebrow">MÉTHODE</span><h2>Un signal réel, une preuve mesurable</h2></div><button className="text-button" onClick={() => setPipelineModal(true)}>Piloter le workflow <ArrowRight size={16} /></button></div>
            <div className="workflow-grid">
              {steps.map(({ n, title, text, label, icon: Icon }, index) => (
                <article key={title}>
                  <div className="step-line"><span>{n}</span>{index < steps.length - 1 && <i />}</div>
                  <div className="step-icon"><Icon size={20} /></div><h3>{title}</h3><p>{text}</p><strong>{typeof workflowValues[index] === "number" ? Number(workflowValues[index]).toLocaleString("fr-FR") : workflowValues[index]}</strong><small>{label}</small>
                </article>
              ))}
            </div>
          </section>

          <section className="split-grid">
            <article className="panel chart-panel">
              <div className="panel-head"><div><span className="eyebrow">ACTIVITÉ</span><h2>Couverture du corpus</h2></div><button className="select-button">7 derniers jours <ChevronDown size={14} /></button></div>
              <div className="chart-wrap chart-empty"><Activity size={27} /><strong>Historique en attente</strong><span>La courbe apparaîtra après les premières collectes et validations.</span></div>
            </article>
            <article className="panel source-panel">
              <div className="panel-head"><div><span className="eyebrow">SOURCES</span><h2>Qualité des signaux</h2></div><button className="icon-button"><MoreHorizontal size={18} /></button></div>
              {sources.map((source) => <div className="source-row" key={source.id}><span className="source-logo logo-G">{source.kind.slice(0, 1).toUpperCase()}</span><div><strong>{source.name}</strong><small>{source.kind.toUpperCase()}</small></div><div className="quality"><span><i style={{ width: source.enabled ? "100%" : "0%" }} /></span><b>{source.enabled ? "Active" : "Pause"}</b></div></div>)}
              {sources.length === 0 && <div className="source-empty">Aucune source connectée.</div>}
              <button className="source-add" onClick={() => setSeedModal(true)}><Plus size={16} /> Ajouter des mots-clés</button>
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
      {modal && <PromptModal projectId={projectId} onClose={() => setModal(false)} onSubmit={reloadAfterPromptTest} />}
      {seedModal && <SeedModal projectId={projectId} onClose={() => setSeedModal(false)} />}
      {datasetModal && <DatasetBuilderModal projectId={projectId} onClose={() => setDatasetModal(false)} />}
      {pipelineModal && <PipelineModal projectId={projectId} onClose={() => setPipelineModal(false)} />}
      {reviewModal && <ManualReviewModal projectId={projectId} onClose={() => setReviewModal(false)} />}
      {costsModal && <CostsModal projectId={projectId} onClose={() => setCostsModal(false)} />}
      {docsModal && <DocumentationModal onClose={() => setDocsModal(false)} />}
      {executionModal && <ExecutionCenterModal projectId={projectId} onClose={() => setExecutionModal(false)} />}
      {exportsModal && <ExportsModal projectId={projectId} onClose={() => setExportsModal(false)} />}
      {workspaceModal && <WorkspaceModal onClose={() => setWorkspaceModal(false)} onCreated={workspaceCreated} />}
    </div>
  );
}

function PromptModal({ projectId, onClose, onSubmit }: { projectId: string | null; onClose: () => void; onSubmit: (prompt: string) => void }) {
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
      const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, provider, engine, country: "FR", language: "fr", projectId }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Analyse impossible.");
      onSubmit(prompt.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analyse impossible.");
    } finally {
      setLoading(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal" onMouseDown={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); void submit(); }}><div className="modal-head"><div><span className="eyebrow">TEST ISOLÉ</span><h2>Tester un prompt</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label>Prompt utilisateur<textarea autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ex. Quelles chaussures de trail choisir pour débuter ?" rows={4} /></label><div className="form-row"><label>Fournisseur<select value={provider} onChange={(e) => setProvider(e.target.value)}><option value="brightdata">Bright Data</option><option value="oxylabs">Oxylabs</option></select></label><label>Moteur<select value={engine} onChange={(e) => setEngine(e.target.value)}><option value="chatgpt">ChatGPT</option><option value="perplexity">Perplexity</option><option value="gemini">Gemini</option><option value="google_ai_mode">Google AI Mode</option></select></label></div>{error && <p className="form-error">{error}</p>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Annuler</button><button className="primary" disabled={!prompt.trim() || loading}><FlaskConical size={17} /> {loading ? "Analyse…" : "Lancer l'analyse"}</button></div></form></div>;
}
