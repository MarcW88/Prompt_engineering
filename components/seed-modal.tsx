"use client";

import { useState } from "react";
import { Database, FileUp, Play, Upload, X } from "lucide-react";
import readExcelFile from "read-excel-file";
import { parseSeedText, type SeedType } from "@/lib/data/seeds";

const sourceLabels: Record<string, string> = {
  reddit: "Reddit",
  forum: "Forums",
  serp: "PAA & suggestions",
  review: "Trustpilot & avis",
};

const defaultGscPattern = "\\b(comment|pourquoi|quel|quelle|quels|quelles|meilleur|meilleure|avis|problème|comparatif|choisir|alternative|vs)\\b";

function lines(value: string) {
  return value.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean);
}

function seedFileValues(text: string) {
  return text.replace(/^\uFEFF/, "").split(/\r?\n/).flatMap((line) => {
    const first = line.split(/[,;\t]/)[0]?.trim() ?? "";
    const normalized = first.toLowerCase();
    if (!first || ["keyword", "keywords", "mot-clé", "mots-clés", "query", "requête", "requêtes"].includes(normalized)) return [];
    return [first];
  });
}

export function SeedModal({ projectId, onClose }: { projectId: string | null; onClose: () => void }) {
  const [text, setText] = useState("");
  const [seedType, setSeedType] = useState<SeedType>("keyword");
  const [priority, setPriority] = useState(70);
  const [sources, setSources] = useState(["reddit", "forum", "serp", "review"]);
  const [queryBudget, setQueryBudget] = useState(10);
  const [subreddits, setSubreddits] = useState("running\ncycling\nCampingGear\nFitness\nfrance\nAskFrance");
  const [forumUrls, setForumUrls] = useState("https://www.randonner-leger.org/forum/\nhttps://www.skipass.com/forums/\nhttps://forum.velotaf.com/\nhttps://forum.hardware.fr/hfr/Discussions/Sports/");
  const [trustpilotUrl, setTrustpilotUrl] = useState("https://fr.trustpilot.com/review/www.decathlon.fr");
  const [serpTemplates, setSerpTemplates] = useState("{theme} {brand} avis\n{theme} {brand} qualité\nmeilleur {theme} {brand}\n{brand} vs {competitor}\nproblème {brand}\nalternative {brand} {theme}");
  const [gscPattern, setGscPattern] = useState(defaultGscPattern);
  const [status, setStatus] = useState("");
  const [fileStatus, setFileStatus] = useState("");
  const [gscStatus, setGscStatus] = useState("");
  const [loading, setLoading] = useState(false);

  function toggleSource(source: string) {
    setSources((current) => current.includes(source) ? current.filter((item) => item !== source) : [...current, source]);
  }

  async function importSeedFile(file: File) {
    setFileStatus("Lecture du fichier…");
    try {
      let values: string[] = [];
      if (/\.(xlsx|xls)$/i.test(file.name)) {
        const rows = await readExcelFile(file);
        values = rows.flatMap((row) => {
          const first = String(row[0] ?? "").trim();
          const normalized = first.toLowerCase();
          return !first || ["keyword", "keywords", "mot-clé", "mots-clés", "query", "requête", "requêtes"].includes(normalized) ? [] : [first];
        });
      } else {
        values = seedFileValues(await file.text());
      }
      if (!values.length) throw new Error("Aucun mot-clé trouvé dans la première colonne.");
      setText((current) => [...current.split(/\r?\n/).map((item) => item.trim()).filter(Boolean), ...values].join("\n"));
      setFileStatus(`${values.length} mots-clés importés depuis ${file.name}.`);
    } catch (reason) {
      setFileStatus(reason instanceof Error ? reason.message : "Fichier impossible à lire.");
    }
  }

  async function importGsc(file: File) {
    setGscStatus("Import en cours…");
    const form = new FormData();
    form.append("file", file);
    form.append("minWords", "10");
    form.append("queryPattern", gscPattern);
    if (projectId) form.append("projectId", projectId);
    try {
      const response = await fetch("/api/sources/gsc", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Import impossible.");
      setGscStatus(`${data.parsed} requêtes détectées${data.configured ? `, ${data.imported} importées` : " — connectez Supabase pour les sauvegarder"}.`);
    } catch (reason) {
      setGscStatus(reason instanceof Error ? reason.message : "Import impossible.");
    }
  }

  async function submit() {
    if (!projectId) { setStatus("Créez et connectez d'abord un workspace Supabase."); return; }
    const seeds = parseSeedText(text, { seedType, priority, source: "dashboard" });
    if (!seeds.length) { setStatus("Ajoutez au moins un mot-clé ou importez un fichier."); return; }
    setLoading(true);
    setStatus("Enregistrement des seeds…");
    try {
      const seedResponse = await fetch("/api/seeds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, seeds }) });
      const seedData = await seedResponse.json();
      if (!seedResponse.ok) throw new Error(seedData.error ?? "Import impossible.");
      setStatus("Création du job de collecte…");
      const sourceConfig = {
        subreddits: lines(subreddits),
        forum_urls: lines(forumUrls),
        trustpilot_url: trustpilotUrl.trim(),
        serp_templates: lines(serpTemplates),
      };
      const jobResponse = await fetch("/api/jobs/collect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, sources, queryBudget, sourceConfig }) });
      const jobData = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(jobData.error ?? "Job impossible.");
      setStatus(`${seeds.length} seeds enregistrés. Collecte mise en file pour ${sources.map((source) => sourceLabels[source]).join(", ")}.`);
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Opération impossible.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal seed-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <div className="modal-head">
          <div><span className="eyebrow">COLLECTE CONFIGURÉE</span><h2>Nouvelle collecte</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>

        <div className="builder-guide">
          <strong>Sur quoi repose la collecte ?</strong>
          <ol>
            <li>Les seeds servent à générer les recherches Reddit, forums et SERP.</li>
            <li>Les URL/subreddits ci-dessous remplacent la configuration par défaut pour ce job.</li>
            <li>GSC importe directement les requêtes filtrées par la regex.</li>
            <li>Trustpilot utilise DataForSEO avec l’URL de page avis fournie.</li>
          </ol>
        </div>

        <label>Mots-clés, un par ligne<textarea autoFocus rows={5} value={text} onChange={(event) => setText(event.target.value)} placeholder={"chaussures trail débutant\nveste randonnée imperméable\nmal au genou après running"} /><small>Colle une liste ou importe un fichier CSV/Excel ; la première colonne est utilisée.</small></label>
        <label className="upload-zone"><FileUp size={19} /><span>Importer des mots-clés CSV, TXT ou Excel</span><input type="file" accept=".csv,.txt,.xls,.xlsx,text/csv,text/plain" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importSeedFile(file); }} /></label>
        {fileStatus && <p className="import-status">{fileStatus}</p>}

        <div className="form-row">
          <label>Type<select value={seedType} onChange={(event) => setSeedType(event.target.value as SeedType)}><option value="keyword">Mot-clé</option><option value="theme">Thème</option><option value="brand">Marque</option><option value="competitor">Concurrent</option><option value="product">Produit</option><option value="problem">Problème</option></select><small>Le même type est appliqué à toutes les lignes importées.</small></label>
          <label>Priorité<input type="number" min="0" max="100" value={priority} onChange={(event) => setPriority(Number(event.target.value))} /><small>Les seeds les plus prioritaires sont planifiés en premier.</small></label>
        </div>
        <label>Budget max de requêtes par source<input type="number" min="1" max="200" value={queryBudget} onChange={(event) => setQueryBudget(Number(event.target.value))} /><small>Limite les recherches planifiées sur chaque source sélectionnée.</small></label>

        <fieldset><legend>Sources à interroger</legend>{Object.entries(sourceLabels).map(([source, label]) => <label className="check-option" key={source}><input type="checkbox" checked={sources.includes(source)} onChange={() => toggleSource(source)} /> {label}</label>)}<small>Seules les sources cochées seront interrogées par le worker.</small></fieldset>

        {sources.includes("reddit") && <label>Subreddits, un par ligne<textarea rows={4} value={subreddits} onChange={(event) => setSubreddits(event.target.value)} /><small>Noms sans `r/`. Ces valeurs remplacent la liste par défaut du job.</small></label>}
        {sources.includes("forum") && <label>URLs de forums, une par ligne<textarea rows={4} value={forumUrls} onChange={(event) => setForumUrls(event.target.value)} /><small>Chaque URL est utilisée via des recherches Google ciblées site:domaine.</small></label>}
        {sources.includes("review") && <label>URL Trustpilot<input value={trustpilotUrl} onChange={(event) => setTrustpilotUrl(event.target.value)} /><small>Exemple : https://fr.trustpilot.com/review/www.decathlon.fr</small></label>}
        {sources.includes("serp") && <label>Templates SERP, un par ligne<textarea rows={4} value={serpTemplates} onChange={(event) => setSerpTemplates(event.target.value)} /><small>Variables disponibles : {"{theme}"}, {"{brand}"}, {"{brand_variant}"}, {"{competitor}"}.</small></label>}

        <div className="gsc-box">
          <label>Regex Search Console<input value={gscPattern} onChange={(event) => setGscPattern(event.target.value)} /><small>Regex préremplie pour garder les requêtes conversationnelles. Tu peux la modifier.</small></label>
          <label className="upload-zone"><Upload size={19} /><span>Importer un export CSV Google Search Console</span><input type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importGsc(file); }} /></label>
          {gscStatus && <p className="import-status">{gscStatus}</p>}
        </div>

        {status && <p className="import-status">{status}</p>}
        <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Fermer</button><button className="primary" disabled={loading || !text.trim() || !sources.length}><Database size={17} />{loading ? "Préparation…" : "Enregistrer & collecter"}<Play size={14} /></button></div>
      </form>
    </div>
  );
}
