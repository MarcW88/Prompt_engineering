"use client";

import { useEffect, useRef, useState } from "react";
import { Download, X } from "lucide-react";
import { estimateCampaign, type CampaignPlan } from "@/lib/data/campaign-estimate";

type Props = {
  onClose: () => void;
  initialTarget?: number;
  initialBudget?: number;
  initialCollection?: number;
  sources?: string[];
};
const eur = (value: number) => value.toLocaleString("fr-BE", { style: "currency", currency: "EUR", maximumFractionDigits: 4 });
const labels: Record<string, string> = { reddit: "Reddit", forum: "Forums", serp: "PAA / suggestions", review: "Avis", facebook: "Facebook", instagram: "Instagram", linkedin: "LinkedIn", x: "X" };

export function CampaignCostPlanner({ onClose, initialTarget = 200, initialBudget = 20, initialCollection, sources = [] }: Props) {
  const dialog = useRef<HTMLElement>(null);
  const [plan, setPlan] = useState<CampaignPlan>(() => ({
    targetPrompts: initialTarget, acceptancePercent: 50, runsPerFinal: 3, reconstructedPrompts: 0,
    candidatesPerTarget: 3, engines: [{ name: "ChatGPT / Bright Data", eurPerRun: 0.02 }],
    collectionEur: initialCollection ?? null, preparationEur: null, cloudEur: null, iclEurPerTarget: null,
    alreadyCommittedEur: null, budgetEur: initialBudget, contingencyPercent: 20,
  }));
  const [promptKind, setPromptKind] = useState("mixte");
  const [model, setModel] = useState("");
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const controls = [...(dialog.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input, select, summary, a[href]") ?? [])].filter((element) => element.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); previous?.focus(); };
  }, [onClose]);
  let estimate: ReturnType<typeof estimateCampaign> | null = null;
  let error = "";
  try { estimate = estimateCampaign(plan); } catch (reason) { error = reason instanceof Error ? reason.message : "Paramètres invalides."; }
  function number(key: keyof CampaignPlan, value: string) {
    setPlan((current) => ({ ...current, [key]: value === "" ? NaN : Number(value) }));
  }
  function amount(key: keyof CampaignPlan, value: string) {
    setPlan((current) => ({ ...current, [key]: value === "" ? null : Number(value) }));
  }
  function download() {
    if (!estimate) return;
    const blob = new Blob([JSON.stringify({ exportedAt: new Date().toISOString(), kind: "prévision non contractuelle", promptKind, model, sources, parameters: plan, estimate, rates: "Valeurs saisies / hypothèses configurées. Le défaut 0,02 €/run vient du Dataset Builder, pas d’une facture fournisseur." }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "prevision-campagne.json"; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section ref={dialog} role="dialog" aria-modal="true" aria-labelledby="campaign-planner-title" className="modal campaign-planner" onMouseDown={(event) => event.stopPropagation()}>
      <div className="modal-head"><div><span className="eyebrow">AVANT DE LANCER</span><h2 id="campaign-planner-title">Combien coûtera mon analyse ?</h2></div><button type="button" className="icon-button" aria-label="Fermer l’estimation" onClick={onClose}><X size={19} /></button></div>
      <p>Estime le travail nécessaire pour obtenir ton portefeuille final, quel que soit son volume ou le format des prompts. Cette simulation ne lance aucun appel et ne modifie pas ton budget.</p>
      <div className="form-row">
        <label>Prompts finaux souhaités<input type="number" min="1" max="10000" value={Number.isFinite(plan.targetPrompts) ? plan.targetPrompts : ""} onChange={(event) => { const value = Number(event.target.value); setPlan((current) => ({ ...current, targetPrompts: event.target.value === "" ? NaN : value, reconstructedPrompts: Math.min(current.reconstructedPrompts, value) })); }} /></label>
        <label>Format des prompts<select value={promptKind} onChange={(event) => setPromptKind(event.target.value)}><option value="mixte">Mixte</option><option value="court">Questions courtes / longue traîne</option><option value="contextuel">Demandes contextualisées</option></select></label>
        <label>Passages par prompt final<select value={plan.runsPerFinal} onChange={(event) => number("runsPerFinal", event.target.value)}>{[1, 3, 5].map((n) => <option key={n} value={n}>{n}{n === 1 ? " — première mesure" : " — répétitions incluses"}</option>)}</select></label>
      </div>
      <small>La longueur seule ne fixe pas le prix. Renseigne un prix par exécution incluant les tokens et recherches du modèle choisi. Une réponse longue peut coûter davantage avec une API facturée aux tokens.</small>
      <h3>Sources et préparation</h3>
      <p>{sources.length ? `Sources du setup conservées : ${sources.map((s) => labels[s] ?? s).join(" · ")}.` : "Inclure les sources souhaitées, réseaux sociaux compris, dans l’enveloppe de collecte."}</p>
      <div className="form-row">
        <label>Collecte prévue — toutes sources (€)<input type="number" min="0" step="0.01" placeholder="Inconnu" value={plan.collectionEur ?? ""} onChange={(event) => amount("collectionEur", event.target.value)} /><small>{initialCollection != null ? "Repris de l’estimateur du setup ; hypothèse indicative, à confirmer." : "Reprendre l’estimation de la collecte prévue, pas les dépenses déjà effectuées."}</small></label>
        <label>Transformation + embeddings (€)<input type="number" min="0" step="0.01" placeholder="Inconnu" value={plan.preparationEur ?? ""} onChange={(event) => amount("preparationEur", event.target.value)} /><small>Inclure les appels de préparation et les candidats générés.</small></label>
        <label>Infrastructure attribuable (€)<input type="number" min="0" step="0.01" placeholder="Inconnu" value={plan.cloudEur ?? ""} onChange={(event) => amount("cloudEur", event.target.value)} /></label>
      </div>
      <h3>Surfaces et prix unitaires</h3>
      <label>Modèle / référence de tarification<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="Ex. tarif de mon dataset / estimation tokens + web search" /></label>
      {plan.engines.map((engine, index) => <div className="form-row planner-engine" key={index}>
        <label>Surface<select value={engine.name} onChange={(event) => setPlan((current) => ({ ...current, engines: current.engines.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))}>{["ChatGPT / Bright Data", "OpenAI web search", "Gemini / Bright Data", "Google AI Mode / Bright Data"].map((name) => <option key={name}>{name}</option>)}</select></label>
        <label>Estimation par exécution (€)<input type="number" min="0" step="0.001" placeholder="Inconnu" value={engine.eurPerRun ?? ""} onChange={(event) => setPlan((current) => ({ ...current, engines: current.engines.map((item, i) => i === index ? { ...item, eurPerRun: event.target.value === "" ? null : Number(event.target.value) } : item) }))} /></label>
        <button type="button" className="secondary" disabled={plan.engines.length === 1} aria-label={`Retirer ${engine.name}`} onClick={() => setPlan((current) => ({ ...current, engines: current.engines.filter((_, i) => i !== index) }))}>Retirer</button>
      </div>)}
      <button type="button" className="secondary" disabled={plan.engines.length >= 4} onClick={() => setPlan((current) => ({ ...current, engines: [...current.engines, { name: ["ChatGPT / Bright Data", "OpenAI web search", "Gemini / Bright Data", "Google AI Mode / Bright Data"].find((name) => !current.engines.some((e) => e.name === name))!, eurPerRun: null }] }))}>Ajouter un moteur</button>
      <p className="cost-disclaimer">0,02 €/exécution est l’hypothèse initiale du Dataset Builder, pas un tarif fournisseur vérifié. Un champ vide signifie « inconnu » ; saisir 0 signifie que tu assumes explicitement un coût nul. Les coûts payés restent consultables dans « Coûts réels ».</p>
      <details><summary>Hypothèses de sélection et reconstruction</summary>
        <div className="form-row">
          <label>Candidats finalement retenus (%)<input type="number" min="1" max="100" value={Number.isFinite(plan.acceptancePercent) ? plan.acceptancePercent : ""} onChange={(event) => number("acceptancePercent", event.target.value)} /><small>50 % est une hypothèse modifiable, non calibrée. Les candidats rejetés coûtent aussi un premier passage.</small></label>
          <label>Dont prompts issus de reconstruction<input type="number" min="0" max={plan.targetPrompts} value={Number.isFinite(plan.reconstructedPrompts) ? plan.reconstructedPrompts : ""} onChange={(event) => number("reconstructedPrompts", event.target.value)} /><small>Inclus dans le total final, jamais ajoutés en doublon.</small></label>
          <label>Candidats par cible de reconstruction<select value={plan.candidatesPerTarget} onChange={(event) => number("candidatesPerTarget", event.target.value)}>{[3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select></label>
          <label>Retrieval + ICL par cible (€)<input type="number" min="0" step="0.001" placeholder="Inconnu" value={plan.iclEurPerTarget ?? ""} onChange={(event) => amount("iclEurPerTarget", event.target.value)} /></label>
        </div>
        <p>Les candidats reconstruits et une baseline par cible sont testés sur la première surface listée. Leur premier run est réutilisé dans les répétitions. Les autres surfaces ne testent que les versions retenues. Cette hypothèse de campagne doit être traduite en jobs ; elle ne configure pas automatiquement le worker.</p>
      </details>
      <h3>Budget et marge d’incertitude</h3>
      <div className="form-row">
        <label>Déjà engagé sur le projet (€)<input type="number" min="0" step="0.01" placeholder="À vérifier dans les coûts" value={plan.alreadyCommittedEur ?? ""} onChange={(event) => amount("alreadyCommittedEur", event.target.value)} /><small>Confirmé + consommé non rapproché + réservations existantes. Ne pas inclure ici les mêmes dépenses futures que le plan.</small></label>
        <label>Plafond envisagé (€)<input type="number" min="0" step="1" placeholder="Non défini" value={plan.budgetEur ?? ""} onChange={(event) => amount("budgetEur", event.target.value)} /></label>
        <label>Marge sur le prévisionnel (%)<input type="number" min="0" max="100" value={Number.isFinite(plan.contingencyPercent) ? plan.contingencyPercent : ""} onChange={(event) => number("contingencyPercent", event.target.value)} /></label>
      </div>
      {error && <p role="alert" className="form-error">{error}</p>}
      {estimate && <>
        <div className={`dataset-estimate ${estimate.complete ? "good" : "warn"}`} aria-live="polite">
          <p><strong>{estimate.complete ? "Prévision renseignée" : "Prévision partielle"} : {eur(estimate.forecastEur)}</strong> {estimate.complete ? "pour le travail à venir, marge incluse." : "de postes chiffrés, marge incluse ; ce montant n’est pas un total complet."}</p>
          <p>{estimate.plannedExecutions.toLocaleString("fr-FR")} exécutions prévues · {estimate.discoveryCandidates} candidats issus des sources · {estimate.reconstructionCandidates} candidats reconstruits.</p>
          {estimate.unknownLines.length > 0 && <p>À chiffrer : {estimate.unknownLines.join(" ; ")}.</p>}
          <p>Total projet prévisionnel : <strong>{estimate.totalProjectEur === null ? "incomplet — coûts ou engagement à renseigner" : eur(estimate.totalProjectEur)}</strong>.</p>
          {estimate.remainingEur !== null && <p>{estimate.exceedsBudget ? `Dépassement prévisionnel du plafond : ${eur(-estimate.remainingEur)}.` : `Écart prévisionnel sous le plafond : ${eur(estimate.remainingEur)}.`} Ce calcul ne garantit pas le blocage des appels.</p>}
          {estimate.reconstructionBatches > 1 && <p>Reconstruction : {estimate.reconstructionTargets} cibles, soit au moins {estimate.reconstructionBatches} jobs (limite actuelle : 10 cibles/job).</p>}
        </div>
        <div className="planner-table-wrap"><table className="planner-table"><caption>Prix prévisionnel par opération — hypothèses saisies</caption><thead><tr><th>Poste</th><th>Quantité</th><th>Prix unitaire</th><th>Sous-total</th></tr></thead><tbody>{estimate.lines.filter((line) => line.quantity > 0).map((line) => <tr key={line.key}><td>{line.label}</td><td>{line.quantity} {line.unit}</td><td>{line.unitEur === null ? "Inconnu" : eur(line.unitEur)}</td><td>{line.totalEur === null ? "À chiffrer" : eur(line.totalEur)}</td></tr>)}<tr><th colSpan={3}>Marge d’incertitude ({plan.contingencyPercent} %)</th><td>{eur(estimate.contingencyEur)}</td></tr></tbody></table></div>
        <p>Le nombre final est un objectif, pas une garantie : les sources peuvent ne pas fournir autant de besoins distincts. Ce calcul ne mesure pas la couverture des seeds et ne crée aucun tarif « réel » à partir d’un score.</p>
      </>}
      <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Revenir sans modifier le setup</button><button type="button" className="primary" disabled={!estimate} onClick={download}><Download size={16} /> Exporter la prévision JSON</button></div>
    </section>
  </div>;
}
