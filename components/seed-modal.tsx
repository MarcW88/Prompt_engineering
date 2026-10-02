"use client";

import { useMemo, useState } from "react";
import { Database, FileUp, Play, Upload, X } from "lucide-react";
import readExcelFile from "read-excel-file";
import { parseSeedText, type SeedType } from "@/lib/data/seeds";

const sourceLabels: Record<string, string> = {
  reddit: "Reddit",
  forum: "Forums",
  serp: "PAA & suggestions",
  review: "Trustpilot & avis",
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  x: "X / Twitter",
};

const defaultGscPattern = "^(?:\\S+\\s+){9,}\\S+$";

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

export function SeedModal({ projectId, onClose, onSubmitted }: { projectId: string | null; onClose: () => void; onSubmitted?: () => void }) {
  const [text, setText] = useState("");
  const [seedType, setSeedType] = useState<SeedType>("keyword");
  const [priority, setPriority] = useState(70);
  const [sources, setSources] = useState(["reddit", "forum", "serp", "review"]);
  const [queryBudget, setQueryBudget] = useState(10);
  const [brandName, setBrandName] = useState("");
  const [domain, setDomain] = useState("");
  const [market, setMarket] = useState("BE");
  const [languages, setLanguages] = useState("fr");
  const [brandVariants, setBrandVariants] = useState("");
  const [themes, setThemes] = useState("");
  const [competitors, setCompetitors] = useState("");
  const [subreddits, setSubreddits] = useState("");
  const [forumUrls, setForumUrls] = useState("");
  const [trustpilotUrl, setTrustpilotUrl] = useState("");
  const [facebookUrls, setFacebookUrls] = useState("");
  const [instagramUrls, setInstagramUrls] = useState("");
  const [linkedinUrls, setLinkedinUrls] = useState("");
  const [xUrls, setXUrls] = useState("");
  const [serpTemplates, setSerpTemplates] = useState("{theme} {brand} avis\n{theme} {brand} qualité\nmeilleur {theme} {brand}\n{brand} vs {competitor}\nproblème {brand}\nalternative {brand} {theme}");
  const [gscPattern, setGscPattern] = useState(defaultGscPattern);
  const [status, setStatus] = useState("");
  const [fileStatus, setFileStatus] = useState("");
  const [gscStatus, setGscStatus] = useState("");
  const [loading, setLoading] = useState(false);

  function toggleSource(source: string) {
    setSources((current) => current.includes(source) ? current.filter((item) => item !== source) : [...current, source]);
  }

  const plannedRequests = useMemo(() => {
    const platformCounts = {
      reddit: lines(subreddits).length,
      forum: lines(forumUrls).length,
      facebook: lines(facebookUrls).length,
      instagram: lines(instagramUrls).length,
      linkedin: lines(linkedinUrls).length,
      x: lines(xUrls).length,
    };
    const requests =
      (sources.includes("reddit") ? queryBudget * Math.max(1, platformCounts.reddit) : 0) +
      (sources.includes("forum") ? queryBudget * Math.max(1, platformCounts.forum) : 0) +
      (sources.includes("serp") ? queryBudget : 0) +
      (sources.includes("facebook") ? queryBudget * Math.max(1, platformCounts.facebook) : 0) +
      (sources.includes("instagram") ? queryBudget * Math.max(1, platformCounts.instagram) : 0) +
      (sources.includes("linkedin") ? queryBudget * Math.max(1, platformCounts.linkedin) : 0) +
      (sources.includes("x") ? queryBudget * Math.max(1, platformCounts.x) : 0);
    return requests + (sources.includes("review") ? Math.min(10, queryBudget) : 0);
  }, [facebookUrls, forumUrls, instagramUrls, linkedinUrls, queryBudget, sources, subreddits, xUrls]);

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
    if (!brandName.trim()) { setStatus("Indique la marque analysée avant de lancer la collecte."); return; }
    setLoading(true);
    setStatus("Enregistrement des seeds…");
    try {
      const seedResponse = await fetch("/api/seeds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, seeds }) });
      const seedData = await seedResponse.json();
      if (!seedResponse.ok) throw new Error(seedData.error ?? "Import impossible.");
      setStatus("Création du job de collecte…");
      const sourceConfig = {
        client_name: brandName.trim(),
        domain: domain.trim(),
        market: market.trim().toUpperCase(),
        languages: lines(languages).map((item) => item.toLowerCase()),
        brand_variants: lines(brandVariants),
        themes: lines(themes),
        competitors: lines(competitors),
        subreddits: lines(subreddits),
        forum_urls: lines(forumUrls),
        trustpilot_url: trustpilotUrl.trim(),
        facebook_urls: lines(facebookUrls),
        instagram_urls: lines(instagramUrls),
        linkedin_urls: lines(linkedinUrls),
        x_urls: lines(xUrls),
        serp_templates: lines(serpTemplates),
      };
      const jobResponse = await fetch("/api/jobs/collect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, sources, queryBudget, sourceConfig }) });
      const jobData = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(jobData.error ?? "Job impossible.");
      setStatus(`${seeds.length} seeds enregistrés. Collecte mise en file pour ${sources.map((source) => sourceLabels[source]).join(", ")}.`);
      onSubmitted?.();
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
            <li>Les seeds servent à générer les recherches Reddit, forums, réseaux sociaux et SERP.</li>
            <li>Le budget limite les requêtes par plateforme : Reddit = subreddits × budget ; forums = URLs × budget ; SERP = budget total ; Trustpilot = maximum {Math.min(10, queryBudget)} pages.</li>
            <li>Estimation actuelle : <b>{plannedRequests.toLocaleString("fr-FR")} requêtes/planifications</b> avant déduplication et résultats vides.</li>
            <li>Les réseaux sociaux utilisent les datasets Bright Data configurés côté worker.</li>
          </ol>
        </div>

        <div className="form-row">
          <label>Marque analysée<input value={brandName} onChange={(event) => setBrandName(event.target.value)} placeholder="Pairi Daiza" /><small>Utilisée dans les templates SERP et les métadonnées.</small></label>
          <label>Domaine<input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="pairidaiza.eu" /><small>Domaine principal de la marque.</small></label>
        </div>
        <div className="form-row">
          <label>Variantes de marque<textarea rows={2} value={brandVariants} onChange={(event) => setBrandVariants(event.target.value)} placeholder={"Pairi Daiza\npairidaiza"} /><small>Une variante par ligne.</small></label>
          <label>Thèmes<textarea rows={2} value={themes} onChange={(event) => setThemes(event.target.value)} placeholder={"zoo\nparc animalier\nbillet d'entrée"} /><small>Utilisés pour la détection et les templates.</small></label>
        </div>
        <div className="form-row">
          <label>Concurrents<textarea rows={2} value={competitors} onChange={(event) => setCompetitors(event.target.value)} placeholder={"Zoo de Beauval\nPlanckendael"} /><small>Optionnel, utile pour les comparaisons.</small></label>
          <div className="form-row compact"><label>Marché<input value={market} onChange={(event) => setMarket(event.target.value)} placeholder="BE" /><small>Code pays.</small></label><label>Langues acceptées<input value={languages} onChange={(event) => setLanguages(event.target.value)} placeholder="fr,nl" /><small>Séparées par virgule ; les autres langues sont exclues.</small></label></div>
        </div>

        <label>Mots-clés, un par ligne<textarea autoFocus rows={5} value={text} onChange={(event) => setText(event.target.value)} placeholder={"prix pairi daiza\npairi daiza hôtel\naccès fauteuil roulant parc"} /><small>Colle une liste ou importe un fichier CSV/Excel ; la première colonne est utilisée.</small></label>
        <label className="upload-zone"><FileUp size={19} /><span>Importer des mots-clés CSV, TXT ou Excel</span><input type="file" accept=".csv,.txt,.xls,.xlsx,text/csv,text/plain" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importSeedFile(file); }} /></label>
        {fileStatus && <p className="import-status">{fileStatus}</p>}

        <div className="form-row">
          <label>Type<select value={seedType} onChange={(event) => setSeedType(event.target.value as SeedType)}><option value="keyword">Mot-clé</option><option value="theme">Thème</option><option value="brand">Marque</option><option value="competitor">Concurrent</option><option value="product">Produit</option><option value="problem">Problème</option></select><small>Le même type est appliqué à toutes les lignes importées.</small></label>
          <label>Priorité<input type="number" min="0" max="100" value={priority} onChange={(event) => setPriority(Number(event.target.value))} /><small>Les seeds les plus prioritaires sont planifiés en premier.</small></label>
        </div>
        <label>Budget max par plateforme<input type="number" min="1" max="200" value={queryBudget} onChange={(event) => setQueryBudget(Number(event.target.value))} /><small>Recommandé : 5–10 pour un test, 20–50 pour un corpus réaliste, au-delà seulement si le secteur est très discuté. Estimation actuelle : {plannedRequests.toLocaleString("fr-FR")} planifications.</small></label>

        <fieldset><legend>Sources à interroger</legend>{Object.entries(sourceLabels).map(([source, label]) => <label className="check-option" key={source}><input type="checkbox" checked={sources.includes(source)} onChange={() => toggleSource(source)} /> {label}</label>)}<small>Reddit, Facebook, Instagram, LinkedIn et X utilisent les datasets Bright Data configurés côté worker ; forums, SERP et avis utilisent DataForSEO.</small></fieldset>

        {sources.includes("reddit") && <label>Subreddits, un par ligne<textarea rows={4} value={subreddits} onChange={(event) => setSubreddits(event.target.value)} placeholder={"belgique\nzoos\nPlanetZoo"} /><small>Noms sans `r/`. Chaque subreddit peut planifier jusqu’au budget indiqué via Bright Data.</small></label>}
        {sources.includes("forum") && <label>URLs de forums, une par ligne<textarea rows={4} value={forumUrls} onChange={(event) => setForumUrls(event.target.value)} /><small>Chaque URL est utilisée via des recherches Google ciblées site:domaine.</small></label>}
        {sources.includes("review") && <label>URL Trustpilot<input value={trustpilotUrl} onChange={(event) => setTrustpilotUrl(event.target.value)} placeholder="https://www.trustpilot.com/review/pairidaiza.eu" /><small>La marque renseignée ci-dessus sera écrite dans les exports, pas Decathlon.</small></label>}
        {sources.includes("facebook") && <label>Pages/posts Facebook, une URL par ligne<textarea rows={3} value={facebookUrls} onChange={(event) => setFacebookUrls(event.target.value)} placeholder={"https://www.facebook.com/pairidaizaofficial"} /><small>Collector Bright Data Facebook : posts et commentaires publics selon le dataset configuré.</small></label>}
        {sources.includes("instagram") && <label>Profils/posts Instagram, une URL par ligne<textarea rows={3} value={instagramUrls} onChange={(event) => setInstagramUrls(event.target.value)} placeholder={"https://www.instagram.com/pairidaizaofficial/"} /><small>Collector Bright Data Instagram : posts et commentaires publics selon le dataset configuré.</small></label>}
        {sources.includes("linkedin") && <label>Pages/posts LinkedIn, une URL par ligne<textarea rows={3} value={linkedinUrls} onChange={(event) => setLinkedinUrls(event.target.value)} placeholder={"https://www.linkedin.com/company/pairi-daiza/"} /><small>Collector Bright Data LinkedIn : posts et commentaires publics selon le dataset configuré.</small></label>}
        {sources.includes("x") && <label>Comptes/posts X, une URL par ligne<textarea rows={3} value={xUrls} onChange={(event) => setXUrls(event.target.value)} placeholder={"https://x.com/pairidaiza"} /><small>Collector Bright Data X/Twitter : posts et commentaires publics selon le dataset configuré.</small></label>}
        {sources.includes("serp") && <label>Templates SERP, un par ligne<textarea rows={4} value={serpTemplates} onChange={(event) => setSerpTemplates(event.target.value)} /><small>Variables disponibles : {"{theme}"}, {"{seed}"}, {"{brand}"}, {"{brand_variant}"}, {"{competitor}"}.</small></label>}

        <div className="gsc-box">
          <label>Regex Search Console<input value={gscPattern} onChange={(event) => setGscPattern(event.target.value)} /><small>Regex préremplie pour garder les requêtes conversationnelles. Tu peux la modifier.</small></label>
          <label className="upload-zone"><Upload size={19} /><span>Importer un export CSV Google Search Console</span><input type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importGsc(file); }} /></label>
          {gscStatus && <p className="import-status">{gscStatus}</p>}
        </div>

        {status && <p className="import-status">{status}</p>}
        <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Fermer</button><button className="primary" disabled={loading || !text.trim() || !sources.length || !brandName.trim()}><Database size={17} />{loading ? "Préparation…" : "Enregistrer & collecter"}<Play size={14} /></button></div>
      </form>
    </div>
  );
}
