"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Database, FileUp, Play, Target, Upload, X } from "lucide-react";
import readExcelFile from "read-excel-file";
import { parseSeedText, type SeedType } from "@/lib/data/seeds";
import { recommendBudget, estimateCollectionCostEur, recommendConfigForTargetPrompts } from "@/lib/data/budget";

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
  const [minimumSourceSignals, setMinimumSourceSignals] = useState(5);
  const [targetPrompts, setTargetPrompts] = useState(100);
  const [socialPostLimit, setSocialPostLimit] = useState(10);
  const [socialCommentLimit, setSocialCommentLimit] = useState(0);
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
  const [step, setStep] = useState(1);
  const [budgetMode, setBudgetMode] = useState<"automatic" | "manual">("automatic");
  const [customBudgetTotalEur, setCustomBudgetTotalEur] = useState<number | null>(null);
  const [sampleMode, setSampleMode] = useState(true);

  const tierLabels = { light: "Collecte ciblée", standard: "Collecte standard", extended: "Collecte approfondie", segmented: "Audit à segmenter" };
  const stepLabels = ["Compte", "Corpus & budget", "Sources", "Vérification"];

  function nextStep() {
    if (step === 1 && !brandName.trim()) { setStatus("Indique la marque analysée pour continuer."); return; }
    if (step === 2 && !text.trim()) { setStatus("Ajoute ou importe au moins un mot-clé pour continuer."); return; }
    if (step === 3 && !sources.length) { setStatus("Sélectionne au moins une source pour continuer."); return; }
    setStatus("");
    setStep((current) => Math.min(4, current + 1));
  }

  function toggleSource(source: string) {
    setSources((current) => current.includes(source) ? current.filter((item) => item !== source) : [...current, source]);
  }

  const platformCounts = useMemo(() => ({
    reddit: lines(subreddits).length,
    forum: lines(forumUrls).length,
    facebook: lines(facebookUrls).length,
    instagram: lines(instagramUrls).length,
    linkedin: lines(linkedinUrls).length,
    x: lines(xUrls).length,
  }), [facebookUrls, forumUrls, instagramUrls, linkedinUrls, subreddits, xUrls]);

  const plannedRequests = useMemo(() => {
    const requests =
      (sources.includes("reddit") ? queryBudget * Math.max(1, platformCounts.reddit) : 0) +
      (sources.includes("forum") ? queryBudget * Math.max(1, platformCounts.forum) : 0) +
      (sources.includes("serp") ? queryBudget : 0) +
      (sources.includes("facebook") ? queryBudget * Math.max(1, platformCounts.facebook) : 0) +
      (sources.includes("instagram") ? queryBudget * Math.max(1, platformCounts.instagram) : 0) +
      (sources.includes("linkedin") ? queryBudget * Math.max(1, platformCounts.linkedin) : 0) +
      (sources.includes("x") ? queryBudget * Math.max(1, platformCounts.x) : 0);
    return requests + (sources.includes("review") ? Math.min(10, queryBudget) : 0);
  }, [platformCounts, queryBudget, sources]);

  const collectionRecommendation = useMemo(() => recommendBudget({
    seeds: parseSeedText(text, { seedType, priority, source: "dashboard" }).length,
    signals: 0,
    themes: lines(themes).length,
    competitors: lines(competitors).length,
    socialTargets: lines(subreddits).length + lines(facebookUrls).length + lines(instagramUrls).length + lines(linkedinUrls).length + lines(xUrls).length,
    languages: Math.max(1, lines(languages).length),
    markets: 1,
    plannedRequests,
    sources,
    socialPostLimit,
    socialCommentLimit,
    sampleMode,
  }), [competitors, facebookUrls, instagramUrls, languages, linkedinUrls, plannedRequests, priority, sampleMode, seedType, socialCommentLimit, socialPostLimit, sources, subreddits, text, themes, xUrls]);
  const socialPlatformsSelected = sources.some((source) => ["facebook", "instagram", "linkedin", "x", "reddit"].includes(source));
  const recommendedQueryBudget = { light: 3, standard: 5, extended: 10, segmented: 15 }[collectionRecommendation.tier];
  const estimatedCollectionCostEur = useMemo(() => estimateCollectionCostEur({
    sources, plannedRequests, queryBudget, sampleMode, socialTargets: lines(subreddits).length + lines(facebookUrls).length + lines(instagramUrls).length + lines(linkedinUrls).length + lines(xUrls).length, socialPostLimit, socialCommentLimit,
  }), [sources, plannedRequests, queryBudget, sampleMode, subreddits, facebookUrls, instagramUrls, linkedinUrls, xUrls, socialPostLimit, socialCommentLimit]);
  const displayBudgetTotalEur = customBudgetTotalEur ?? collectionRecommendation.totalEur;

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
        social_target_limit: Math.max(1, Math.min(50, queryBudget)),
        social_post_limit: Math.max(1, Math.min(50, socialPostLimit)),
        social_comment_limit: Math.max(0, Math.min(20, socialCommentLimit)),
        minimum_source_signals: Math.max(1, Math.min(50, minimumSourceSignals)),
        budget_total_eur: displayBudgetTotalEur,
        budget_mode: budgetMode,
        sample_mode: sampleMode,
        budget_profile: { tier: collectionRecommendation.tier, score: collectionRecommendation.score, corpus_target: collectionRecommendation.corpusTarget, allocations: collectionRecommendation.allocations },
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
      <form className="modal seed-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); if (step < 4) nextStep(); else void submit(); }}>
        <div className="modal-head">
          <div><span className="eyebrow">COLLECTE · ÉTAPE {step}/4</span><h2>{stepLabels[step - 1]}</h2></div>
          <button type="button" className="icon-button" onClick={onClose}><X size={19} /></button>
        </div>

        <div className="workflow-track collect-wizard">{stepLabels.map((label, index) => <button type="button" key={label} className={`workflow-step ${index + 1 < step ? "done" : index + 1 === step ? "current" : ""}`} onClick={() => index + 1 < step && setStep(index + 1)}><span>{index + 1}</span><strong>{label}</strong></button>)}</div>

        {step === 1 && <>
          <div className="builder-guide"><strong>Définir le périmètre</strong><p>Ces informations adaptent les recherches à la marque, au marché et aux langues réellement utiles.</p></div>
          <div className="form-row"><label>Marque analysée<input autoFocus value={brandName} onChange={(event) => setBrandName(event.target.value)} placeholder="Nom de la marque" /><small>Obligatoire. Utilisée dans les recherches et les exports.</small></label><label>Domaine<input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="client.com" /><small>Domaine principal de la marque.</small></label></div>
          <div className="form-row"><label>Variantes de marque<textarea rows={3} value={brandVariants} onChange={(event) => setBrandVariants(event.target.value)} placeholder={"Nom alternatif\nAncienne marque"} /><small>Ne répète pas la marque principale.</small></label><label>Thèmes<textarea rows={3} value={themes} onChange={(event) => setThemes(event.target.value)} placeholder={"produit\nservice\nproblème client"} /><small>Une ligne par sujet à couvrir.</small></label></div>
          <div className="form-row"><label>Concurrents<textarea rows={3} value={competitors} onChange={(event) => setCompetitors(event.target.value)} placeholder={"Concurrent A\nConcurrent B"} /><small>Optionnel, utile pour les comparaisons.</small></label><div className="form-row compact"><label>Marché<input value={market} onChange={(event) => setMarket(event.target.value)} placeholder="BE" /></label><label>Langues acceptées<input value={languages} onChange={(event) => setLanguages(event.target.value)} placeholder="fr,nl" /><small>Les autres langues seront exclues.</small></label></div></div>
        </>}

        {step === 2 && <>
          <div className="builder-guide"><strong>Constituer le point de départ</strong><p>Les seeds et l’import Search Console alimentent la collecte. Leur nombre n’influe pas sur le coût : il dépend des sources que tu choisiras à l’étape suivante.</p></div>
          <label>Mots-clés, un par ligne<textarea autoFocus rows={7} value={text} onChange={(event) => setText(event.target.value)} placeholder={"question client\nproduit recherché\nproblème rencontré"} /><small>Colle une liste ou importe la première colonne d’un CSV/Excel.</small></label>
          <label className="upload-zone"><FileUp size={19} /><span>Importer des mots-clés CSV, TXT ou Excel</span><input type="file" accept=".csv,.txt,.xls,.xlsx,text/csv,text/plain" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importSeedFile(file); }} /></label>
          {fileStatus && <p className="import-status">{fileStatus}</p>}
          <div className="form-row"><label>Type<select value={seedType} onChange={(event) => setSeedType(event.target.value as SeedType)}><option value="keyword">Mot-clé</option><option value="theme">Thème</option><option value="brand">Marque</option><option value="competitor">Concurrent</option><option value="product">Produit</option><option value="problem">Problème</option></select></label><label>Priorité<input type="number" min="0" max="100" value={priority} onChange={(event) => setPriority(Number(event.target.value))} /></label></div>
          <div className="gsc-box"><label>Regex Search Console<input value={gscPattern} onChange={(event) => setGscPattern(event.target.value)} /></label><label className="upload-zone"><Upload size={19} /><span>Importer un export CSV Google Search Console</span><input type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importGsc(file); }} /></label>{gscStatus && <p className="import-status">{gscStatus}</p>}</div>
          <div className="dataset-estimate good"><p><strong>{tierLabels[collectionRecommendation.tier]}</strong> · {collectionRecommendation.score}/100 de complexité estimée.</p><p>Objectif conseillé : obtenir {collectionRecommendation.corpusTarget[0].toLocaleString("fr-FR")} à {collectionRecommendation.corpusTarget[1].toLocaleString("fr-FR")} signaux pertinents au final. Le coût dépend des sources et cibles choisies à l’étape suivante.</p><div className="form-row compact"><label>Plafond global indicatif (€)<input type="number" min="1" max="30" step="1" value={displayBudgetTotalEur} onChange={(event) => { setCustomBudgetTotalEur(Number(event.target.value)); setBudgetMode("manual"); }} /><small>Recommandation automatique : {collectionRecommendation.totalEur.toFixed(2)} €. Ce plafond couvre tout le workflow, pas seulement la collecte. <button type="button" className="text-button" onClick={() => { setCustomBudgetTotalEur(null); setBudgetMode("automatic"); }}>Réinitialiser</button></small></label></div><p><label className="check-option"><input type="checkbox" checked={sampleMode} onChange={(event) => setSampleMode(event.target.checked)} /> Mode échantillon : répartir le budget de requêtes entre toutes les sources sélectionnées. Un minimum de signaux par source sera garanti à l’étape suivante.</label></p></div>
          <div className="builder-guide"><Target size={17} /><strong>Besoin de N prompts finaux ?</strong></div>
          <div className="form-row compact"><label>Nombre de prompts cibles<input type="number" min="10" max="1000" step="5" value={targetPrompts} onChange={(event) => setTargetPrompts(Number(event.target.value))} /><small>L’estimateur calcule la collecte nécessaire pour aboutir à ce nombre de prompts validés.</small></label><label className="check-option"><input type="checkbox" checked={sampleMode} onChange={(event) => setSampleMode(event.target.checked)} /> Mode échantillon (coût réparti entre les sources)</label><button type="button" className="text-button" onClick={() => {
            const recommendation = recommendConfigForTargetPrompts(targetPrompts, sampleMode);
            setSources(recommendation.sources);
            setQueryBudget(recommendation.queryBudget);
            setMinimumSourceSignals(recommendation.minimumSourceSignals);
            setCustomBudgetTotalEur(recommendation.totalBudgetEur);
            setBudgetMode("manual");
          }}>Appliquer la config recommandée</button></div>
          {(() => {
            const recommendation = recommendConfigForTargetPrompts(targetPrompts, sampleMode);
            const exceedsCap = recommendation.collectionCostEur > recommendation.totalBudgetEur;
            return <div className={`dataset-estimate ${exceedsCap ? "warn" : "good"}`}><p><strong>Config estimée :</strong> {recommendation.estimatedSignals.toLocaleString("fr-FR")} signaux · {recommendation.estimatedClusters.toLocaleString("fr-FR")} clusters · budget requêtes {recommendation.queryBudget} · coût collecte ~{recommendation.collectionCostEur.toFixed(2)} € · plafond global {recommendation.totalBudgetEur.toFixed(2)} €</p><p><small>Sources : {recommendation.sources.map((source) => sourceLabels[source as keyof typeof sourceLabels] ?? source).join(", ")} · part sociale ~{recommendation.socialSharePercent}%</small></p><p><small>{sampleMode ? "Mode échantillon : le budget est réparti entre les sources. Idéal pour tester." : "Mode audit complet : chaque source reçoit le budget affiché. Coût plus élevé mais couverture maximale."}</small></p>{exceedsCap && <p className="warning"><AlertTriangle size={14} /> L’estimation de collecte dépasse le plafond global affiché. Augmente le plafond ou réduis le nombre de prompts cibles.</p>}</div>;
          })()}
        </>}

        {step === 3 && <>
          <div className="builder-guide"><strong>Choisir les sources et leurs limites</strong><p>Sélectionne les plateformes pertinentes. Le budget de requêtes définit le volume d’appels externes. En mode échantillon, il est réparti entre les sources.</p></div>
          <fieldset><legend>Sources à interroger</legend>{Object.entries(sourceLabels).map(([source, label]) => <label className="check-option" key={source}><input type="checkbox" checked={sources.includes(source)} onChange={() => toggleSource(source)} /> {label}</label>)}</fieldset>
          {sources.length > 0 && <label>Budget de requêtes par source<input type="number" min="1" max="200" value={queryBudget} onChange={(event) => setQueryBudget(Number(event.target.value))} /><small>{sampleMode ? "Mode échantillon activé : ce budget sera réparti entre les sources sélectionnées pour toucher un peu de chacune." : "Mode échantillon désactivé : ce budget sera appliqué à chaque source active. Le coût peut vite grimper."} Première passe conseillée : {recommendedQueryBudget}. Estimation actuelle : {plannedRequests.toLocaleString("fr-FR")} planifications payantes maximum. <button type="button" className="text-button" onClick={() => setQueryBudget(recommendedQueryBudget)}>Appliquer {recommendedQueryBudget}</button></small></label>}
          {sources.length > 0 && <div className={`dataset-estimate ${estimatedCollectionCostEur > displayBudgetTotalEur * 0.5 ? "warn" : "good"}`}><p><strong>Estimation de coût de cette collecte : {estimatedCollectionCostEur.toFixed(2)} €</strong></p><p>Ce montant est indicatif. Les sources sociales coûtent plus cher que SERP/Trustpilot. Le plafond global actuel est de {displayBudgetTotalEur.toFixed(2)} €.</p>{estimatedCollectionCostEur > displayBudgetTotalEur * 0.5 && <p className="warning"><AlertTriangle size={14} /> L’estimation dépasse 50 % du plafond global. Réduis les cibles sociales ou le budget de requêtes.</p>}</div>}
          {sources.length > 0 && <label>Minimum de signaux bruts par source<input type="number" min="1" max="50" value={minimumSourceSignals} onChange={(event) => setMinimumSourceSignals(Number(event.target.value))} /><small>Chaque source active essaiera de produire au moins ce nombre de signaux. Peut augmenter légèrement le coût.</small></label>}
          {socialPlatformsSelected && <div className="form-row compact"><label>Posts max par cible sociale<input type="number" min="1" max="50" value={socialPostLimit} onChange={(event) => setSocialPostLimit(Number(event.target.value))} /></label><label>Commentaires par post<input type="number" min="0" max="20" value={socialCommentLimit} onChange={(event) => setSocialCommentLimit(Number(event.target.value))} /><small>0 recommandé pour protéger le budget.</small></label></div>}
          {sources.includes("reddit") && <label>Subreddits<textarea rows={3} value={subreddits} onChange={(event) => setSubreddits(event.target.value)} placeholder={"communaute1\ncommunaute2"} /><small>Noms sans `r/`.</small></label>}
          {sources.includes("forum") && <label>URLs de forums<textarea rows={3} value={forumUrls} onChange={(event) => setForumUrls(event.target.value)} /></label>}
          {sources.includes("review") && <label>URL Trustpilot<input value={trustpilotUrl} onChange={(event) => setTrustpilotUrl(event.target.value)} placeholder="https://www.trustpilot.com/review/client.com" /></label>}
          {sources.includes("facebook") && <label>Posts/reels Facebook précis<textarea rows={3} value={facebookUrls} onChange={(event) => setFacebookUrls(event.target.value)} /><small>Les pages entières sont refusées pour éviter une collecte non bornée.</small></label>}
          {sources.includes("instagram") && <label>Profils/posts Instagram<textarea rows={3} value={instagramUrls} onChange={(event) => setInstagramUrls(event.target.value)} /></label>}
          {sources.includes("linkedin") && <label>Pages/posts LinkedIn<textarea rows={3} value={linkedinUrls} onChange={(event) => setLinkedinUrls(event.target.value)} /></label>}
          {sources.includes("x") && <label>Comptes/posts X<textarea rows={3} value={xUrls} onChange={(event) => setXUrls(event.target.value)} /></label>}
          {sources.includes("serp") && <label>Templates SERP<textarea rows={4} value={serpTemplates} onChange={(event) => setSerpTemplates(event.target.value)} /><small>Variables : {"{theme}"}, {"{seed}"}, {"{brand}"}, {"{brand_variant}"}, {"{competitor}"}.</small></label>}
        </>}

        {step === 4 && <>
          <div className="builder-guide"><strong>Vérifier avant le lancement</strong><p>Cette collecte constitue une première passe. Tu pourras étendre uniquement les sources qui produisent des signaux pertinents.</p></div>
          <div className="dataset-estimate good"><p><strong>{brandName}</strong> · marché {market.toUpperCase()} · langues {lines(languages).join(", ") || "fr"}</p><p>{parseSeedText(text, { seedType, priority, source: "dashboard" }).length.toLocaleString("fr-FR")} seeds · {sources.map((source) => sourceLabels[source]).join(", ")}</p><p><strong>{tierLabels[collectionRecommendation.tier]}</strong> : corpus cible {collectionRecommendation.corpusTarget[0].toLocaleString("fr-FR")}–{collectionRecommendation.corpusTarget[1].toLocaleString("fr-FR")} signaux pertinents.</p><p>Première passe : {plannedRequests.toLocaleString("fr-FR")} planifications maximum · minimum {minimumSourceSignals} signaux bruts par source · {socialPostLimit} posts par cible · {socialCommentLimit} commentaire(s) par post.</p><p>Coût collecte estimé : <strong>{estimatedCollectionCostEur.toFixed(2)} €</strong> · plafond global : {displayBudgetTotalEur.toFixed(2)} € · estimation automatique {collectionRecommendation.totalEur.toFixed(2)} €. Les coûts réels restent contrôlés dans le centre Budget.</p></div>
        </>}

        {status && <p className="import-status">{status}</p>}
        <div className="modal-actions"><button type="button" className="secondary" onClick={() => step === 1 ? onClose() : setStep((current) => current - 1)}>{step === 1 ? "Fermer" : "Retour"}</button>{step < 4 ? <button type="button" className="primary" onClick={nextStep}>Continuer<Play size={14} /></button> : <button className="primary" disabled={loading || !text.trim() || !sources.length || !brandName.trim()}><Database size={17} />{loading ? "Préparation…" : "Confirmer & collecter"}<Play size={14} /></button>}</div>
      </form>
    </div>
  );
}
