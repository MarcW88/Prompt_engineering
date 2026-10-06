"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowRight, BarChart3, BookOpen, ChevronDown, CircleDollarSign, CircleHelp,
  Database, Download, FileSearch, FlaskConical, Layers3, Menu, MoreHorizontal, Plus,
  RotateCcw, Search, Settings, ShieldCheck, Sparkles, Trash2, X,
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
import { ValidationModal } from "./validation-modal";
import { WorkspaceModal } from "./workspace-modal";

const nav = [
  { label: "Vue d'ensemble", icon: BarChart3 },
  { label: "Sources", icon: Database },
  { label: "Questions", icon: CircleHelp },
  { label: "Clusters", icon: Layers3 },
  { label: "Prompts", icon: Sparkles },
  { label: "Analyses", icon: FlaskConical },
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
  const [validationModal, setValidationModal] = useState(false);
  const [workspaceModal, setWorkspaceModal] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [records, setRecords] = useState<PromptRecord[]>([]);
  const [metrics, setMetrics] = useState({ seeds: 0, signals: 0, questions: 0, clusters: 0, prompts: 0, datasets: 0, observations: 0, validations: 0, approved: 0, stability: 0 });
  const [sources, setSources] = useState<Array<{ id: string; name: string; kind: string; enabled: boolean }>>([]);
  const [jobs, setJobs] = useState<Array<{ kind: string; status: string }>>([]);
  const [configured, setConfigured] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("Workspace GEO");
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const filtered = useMemo(() => records.filter((item) => item.prompt.toLowerCase().includes(query.toLowerCase())), [query, records]);
  const activeJob = jobs.find((job) => job.status === "running" || job.status === "pending");
  const nextAction = useMemo(() => {
    if (!projectId) return { title: "Créer un workspace", text: "Le workspace regroupera vos seeds, signaux, questions et prompts.", action: () => setWorkspaceModal(true), button: "Créer" };
    if (activeJob) return { title: "Exécution en cours", text: "Suivez sa progression ou annulez-la si elle est en doublon.", action: () => setExecutionModal(true), button: "Voir la progression" };
    if (!metrics.seeds) return { title: "Nouvelle collecte", text: "Ajoutez vos seeds et choisissez Reddit, forums, PAA, Trustpilot ou GSC.", action: () => setSeedModal(true), button: "Collecter" };
    if (!metrics.signals || !metrics.questions || !metrics.clusters) return { title: "Préparer les questions", text: "Transforme les signaux en questions, puis lance automatiquement le clustering.", action: () => setPipelineModal(true), button: "Ouvrir le workflow" };
    const buildJob = jobs.find((job) => job.kind === "build_dataset");
    const validateJob = jobs.find((job) => job.kind === "validate_dataset");
    if (!metrics.observations && buildJob?.status !== "completed") return { title: "1. Construire le dataset", text: "Sélectionnez un petit échantillon de clusters et lancez les premières exécutions.", action: () => setDatasetModal(true), button: "Ouvrir Dataset Builder" };
    if (!metrics.observations && buildJob?.status === "completed") return { title: "1b. Problème de build", text: "Le dataset s’est terminé mais aucune observation n’a été créée. Vérifiez Piloter les jobs pour l’erreur.", action: () => setExecutionModal(true), button: "Voir l’erreur" };
    if (!metrics.validations && validateJob?.status !== "completed") return { title: "2. Valider le dataset", text: "Relancez les prompts acceptés sur 3 runs pour mesurer la stabilité.", action: () => setValidationModal(true), button: "Ouvrir Validation" };
    if (!metrics.prompts) return { title: "3. Reverse engineering", text: "Reconstruisez des prompts plausibles depuis les fan-outs observés.", action: () => setPipelineModal(true), button: "Reconstruire" };
    if (!metrics.approved) return { title: "4. Revue manuelle", text: "Approuvez, modifiez ou rejetez les prompts avant l’export final.", action: () => setReviewModal(true), button: "Réviser" };
    return { title: "5. Exporter", text: "Téléchargez les prompts approuvés au format Semactic.", action: () => setExportsModal(true), button: "Exporter" };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJob, metrics, projectId]);

  const loadDashboard = useCallback(async (selectedProjectId?: string) => {
    const suffix = selectedProjectId ? `?projectId=${encodeURIComponent(selectedProjectId)}` : "";
    const response = await fetch(`/api/dashboard${suffix}`);
    if (!response.ok) throw new Error("Dashboard indisponible");
    const data = await response.json();
    setConfigured(Boolean(data.configured));
    setProjectId(data.projectId ?? null);
    setProjectName(data.projectName ?? "Workspace GEO");
    setMetrics(data.metrics);
    setSources(data.sources);
    setJobs(data.jobs ?? []);
    setRecords(data.prompts.map((item: { id: string; text: string; provenance: Provenance; confidence: number; status: PromptRecord["status"] }) => ({
      id: item.id.slice(0, 8), prompt: item.text, provenance: item.provenance, confidence: Math.round(Number(item.confidence) * 100), status: item.status,
      engine: "chatgpt", fanOuts: 0, citations: 0, stability: 0,
    })));
  }, []);

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
  }, [loadDashboard]);

  useEffect(() => {
    if (!projectId) return;
    const interval = window.setInterval(() => void loadDashboard(projectId).catch(() => undefined), 15000);
    return () => window.clearInterval(interval);
  }, [loadDashboard, projectId]);

  function latestJob(kind: string) {
    return jobs.find((job) => job.kind === kind);
  }

  function stepState(kind: string, done: boolean, ready = true) {
    const job = latestJob(kind);
    if (job?.status === "running" || job?.status === "pending") return "En cours";
    if (done || job?.status === "completed") return "Terminé";
    return ready ? "Prêt" : "À faire";
  }

  const workflowSteps = [
    { n: "01", title: "Collecte", text: "Reddit, forums, PAA, Trustpilot et GSC.", value: metrics.signals, label: "signaux", icon: Database, status: stepState("collect_sources", metrics.signals > 0, metrics.seeds > 0), action: () => setSeedModal(true) },
    { n: "02", title: "Questions", text: "Signaux nettoyés et transformés en questions.", value: metrics.questions, label: "questions", icon: CircleHelp, status: stepState("transform_signals", metrics.questions > 0, metrics.signals > 0), action: () => setPipelineModal(true) },
    { n: "03", title: "Clusters", text: "Intentions regroupées par similarité.", value: metrics.clusters, label: "clusters", icon: Layers3, status: stepState("cluster_questions", metrics.clusters > 0, metrics.questions > 0), action: () => setPipelineModal(true) },
    { n: "04", title: "Dataset + exécution", text: "Échantillon contrôlé et premières réponses moteurs.", value: metrics.observations, label: "observations", icon: FlaskConical, status: stepState("build_dataset", metrics.observations > 0, metrics.clusters > 0), action: () => setDatasetModal(true) },
    { n: "05", title: "Validation", text: "Runs répétés, reproduction et stabilité.", value: metrics.validations, label: "validations", icon: ShieldCheck, status: stepState("validate_dataset", metrics.validations > 0, metrics.observations > 0), action: () => setPipelineModal(true) },
    { n: "06", title: "Reverse engineering", text: "Prompts plausibles reconstruits depuis les fan-outs.", value: metrics.prompts, label: "prompts", icon: Sparkles, status: stepState("reverse_engineer", false, metrics.validations > 0 || metrics.observations > 0), action: () => setPipelineModal(true) },
    { n: "07", title: "Revue humaine", text: "Approbation, modification ou rejet avant export.", value: metrics.approved, label: "approuvés", icon: FileSearch, status: metrics.approved > 0 ? "Terminé" : metrics.datasets > 0 ? "Prêt" : "À faire", action: () => setReviewModal(true) },
    { n: "08", title: "Export Semactic", text: "Export final des prompts acceptés et approuvés.", value: metrics.approved, label: "exportables", icon: Download, status: metrics.approved > 0 ? "Prêt" : "À faire", action: () => setExportsModal(true) },
  ];

  async function switchWorkspace(id: string) {
    await loadDashboard(id).catch(() => setRecords([]));
  }

  async function workspaceCreated(project: { id: string; name: string }) {
    setProjects((current) => [...current, project]);
    setWorkspaceModal(false);
    await switchWorkspace(project.id);
  }

  async function resetWorkspace() {
    if (!projectId || resetting) return;
    const confirmed = window.confirm(`Réinitialiser « ${projectName} » ? Tous les seeds, signaux, questions, clusters, prompts, analyses, coûts et historiques de jobs seront supprimés de ce workspace. Cette action est irréversible.`);
    if (!confirmed) return;
    setResetting(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/reset`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Réinitialisation impossible.");
      await loadDashboard(projectId);
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "Réinitialisation impossible.");
    } finally {
      setResetting(false);
    }
  }

  async function deleteWorkspace() {
    if (!projectId || resetting) return;
    const typed = window.prompt(`Tapez le nom du workspace « ${projectName} » pour confirmer la suppression définitive. Toutes les données seront perdues.`);
    if (typed !== projectName) return;
    setResetting(true);
    try {
      const response = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Suppression impossible.");
      setProjects((current) => current.filter((project) => project.id !== projectId));
      await loadDashboard();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "Suppression impossible.");
    } finally {
      setResetting(false);
    }
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
          <button type="button" className="workspace-add danger" onClick={() => void resetWorkspace()} disabled={!projectId || resetting} aria-label="Réinitialiser le workspace"><RotateCcw size={15} className={resetting ? "spin" : ""} /></button>
          <button type="button" className="workspace-add danger" onClick={() => void deleteWorkspace()} disabled={!projectId || resetting || projects.length < 2} aria-label="Supprimer le workspace"><Trash2 size={15} /></button>
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

          <section className="next-action">
            <div><span className="eyebrow">PROCHAINE ÉTAPE</span><h2>{nextAction.title}</h2><p>{nextAction.text}</p></div>
            <button className="primary" onClick={nextAction.action}>{nextAction.button}<ArrowRight size={16} /></button>
          </section>

          <section className="workflow-section">
            <div className="section-heading"><div><span className="eyebrow">WORKFLOW COMPLET</span><h2>Où en est le projet ?</h2></div><button className="text-button" onClick={() => setPipelineModal(true)}>Piloter les jobs <ArrowRight size={15} /></button></div>
            <div className="workflow-track">
              {workflowSteps.map(({ n, title, text, label, value, icon: Icon, status, action }, index) => (
                <button type="button" key={title} className={`workflow-step ${status === "Terminé" ? "done" : status === "En cours" ? "current" : status === "Prêt" ? "ready" : ""}`} onClick={action}>
                  <div className="step-line"><span>{n}</span>{index < workflowSteps.length - 1 && <i />}</div>
                  <div className="step-icon"><Icon size={20} /></div><h3>{title}</h3><p>{text}</p><strong>{Number(value).toLocaleString("fr-FR")}</strong><small>{label}</small><em>{status}</em>
                </button>
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
      {seedModal && <SeedModal projectId={projectId} onClose={() => setSeedModal(false)} onSubmitted={() => void loadDashboard(projectId ?? undefined)} />}
      {datasetModal && <DatasetBuilderModal projectId={projectId} onClose={() => setDatasetModal(false)} />}
      {pipelineModal && <PipelineModal projectId={projectId} onClose={() => setPipelineModal(false)} onOpenCollection={() => { setPipelineModal(false); setSeedModal(true); }} onOpenDataset={() => { setPipelineModal(false); setDatasetModal(true); }} onOpenValidation={() => { setPipelineModal(false); setValidationModal(true); }} onOpenReview={() => { setPipelineModal(false); setReviewModal(true); }} onOpenExports={() => { setPipelineModal(false); setExportsModal(true); }} />}
      {reviewModal && <ManualReviewModal projectId={projectId} onClose={() => setReviewModal(false)} />}
      {costsModal && <CostsModal projectId={projectId} onClose={() => setCostsModal(false)} />}
      {docsModal && <DocumentationModal onClose={() => setDocsModal(false)} />}
      {executionModal && <ExecutionCenterModal projectId={projectId} onClose={() => setExecutionModal(false)} />}
      {exportsModal && <ExportsModal projectId={projectId} onClose={() => setExportsModal(false)} />}
      {validationModal && <ValidationModal projectId={projectId} onClose={() => setValidationModal(false)} />}
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
