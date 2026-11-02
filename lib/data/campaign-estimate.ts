// A planning calculation, never a provider quote or a permission to spend.
export type PlannedEngine = { name: string; eurPerRun: number | null };
export type CampaignPlan = {
  targetPrompts: number;
  acceptancePercent: number;
  runsPerFinal: number;
  reconstructedPrompts: number;
  candidatesPerTarget: number;
  engines: PlannedEngine[];
  collectionEur: number | null;
  preparationEur: number | null;
  iclEurPerTarget: number | null;
  cloudEur: number | null;
  alreadyCommittedEur: number | null;
  budgetEur: number | null;
  contingencyPercent: number;
};
export type EstimateLine = { key: string; label: string; quantity: number; unit: string; unitEur: number | null; totalEur: number | null };

function count(value: number, minimum: number, maximum: number) {
  if (!Number.isFinite(value) || value < minimum || value > maximum) throw new Error(`Valeur attendue entre ${minimum} et ${maximum}.`);
  return Math.ceil(value);
}
function money(value: number | null) {
  if (value === null) return null;
  if (!Number.isFinite(value) || value < 0) throw new Error("Un coût doit être positif ou explicitement inconnu.");
  return value;
}
const round = (value: number) => Math.round((value + Number.EPSILON) * 10000) / 10000;

export function estimateCampaign(plan: CampaignPlan) {
  const target = count(plan.targetPrompts, 1, 10000);
  const acceptance = count(plan.acceptancePercent, 1, 100) / 100;
  const repetitions = count(plan.runsPerFinal, 1, 5);
  const reconstructed = count(plan.reconstructedPrompts, 0, target);
  const perTarget = count(plan.candidatesPerTarget, 3, 5);
  const contingency = count(plan.contingencyPercent, 0, 100) / 100;
  if (!plan.engines.length || new Set(plan.engines.map((e) => e.name.trim())).size !== plan.engines.length || plan.engines.some((e) => !e.name.trim())) {
    throw new Error("Choisissez au moins un moteur, avec un nom distinct par surface.");
  }
  const discoveryFinals = target - reconstructed;
  const discoveryCandidates = Math.ceil(discoveryFinals / acceptance);
  const reconstructionTargets = Math.ceil(Math.ceil(reconstructed / acceptance) / perTarget);
  const reconstructionCandidates = reconstructionTargets * perTarget;
  const lines: EstimateLine[] = [];
  function add(key: string, label: string, quantity: number, unit: string, rate: number | null) {
    const unitEur = money(rate);
    // An unused service costs zero even when its price is unknown.
    lines.push({ key, label, quantity, unit, unitEur, totalEur: quantity === 0 ? 0 : unitEur === null ? null : round(quantity * unitEur) });
  }
  add("collection", "Collecte — toutes les sources sélectionnées", 1, "campagne", plan.collectionEur);
  add("preparation", "Transformation, génération et embeddings", 1, "campagne", plan.preparationEur);
  plan.engines.forEach((engine, index) => {
    const rate = money(engine.eurPerRun);
    add(`screen-${index}`, `${engine.name} — premier passage des candidats issus des sources`, discoveryCandidates, "exécutions", rate);
    add(`validation-${index}`, `${engine.name} — répétitions des prompts retenus`, discoveryFinals * (repetitions - 1), "exécutions", rate);
    // Reconstruction candidates and baseline run on the first listed surface.
    // Reuse that screening run: it is not charged a second time as validation.
    add(`reconstruction-${index}`, `${engine.name} — reconstruction et validation`, index === 0
      ? reconstructionCandidates + reconstructed * (repetitions - 1)
      : reconstructed * repetitions, "exécutions", rate);
    if (index === 0) add("baseline", `${engine.name} — baseline de reconstruction`, reconstructionTargets, "exécutions", rate);
  });
  add("icl", "Retrieval et ICL de reconstruction", reconstructionTargets, "cibles", plan.iclEurPerTarget);
  add("cloud", "Infrastructure attribuable à cette campagne", 1, "campagne", plan.cloudEur);
  const unknownLines = lines.filter((line) => line.totalEur === null).map((line) => line.label);
  const subtotalEur = round(lines.reduce((sum, line) => sum + (line.totalEur ?? 0), 0));
  const contingencyEur = round(subtotalEur * contingency);
  const forecastEur = round(subtotalEur + contingencyEur);
  const committed = money(plan.alreadyCommittedEur);
  const budget = money(plan.budgetEur);
  const complete = unknownLines.length === 0;
  const totalProjectEur = complete && committed !== null ? round(forecastEur + committed) : null;
  return {
    targetPrompts: target, discoveryCandidates, reconstructionCandidates, reconstructionTargets,
    reconstructionBatches: Math.ceil(reconstructionTargets / 10),
    plannedExecutions: lines.filter((line) => line.unit === "exécutions").reduce((sum, line) => sum + line.quantity, 0),
    lines, unknownLines, complete, subtotalEur, contingencyEur, forecastEur, totalProjectEur,
    remainingEur: totalProjectEur !== null && budget !== null ? round(budget - totalProjectEur) : null,
    exceedsBudget: totalProjectEur !== null && budget !== null ? totalProjectEur > budget : null,
  };
}


/** Supported planning surfaces; operational availability must be checked before execution. */
export const CAMPAIGN_SURFACES = ["ChatGPT / Bright Data", "OpenAI web search", "Gemini / Bright Data", "Google AI Mode / Bright Data"];
export function fullSurfaceScenario(): PlannedEngine[] {
  return CAMPAIGN_SURFACES.map((name) => ({ name, eurPerRun: 0.02 }));
}
/** Upper configured rate, never an upper bound on the provider bill. Unknown stays unknown. */
export function conservativeEngines(engines: PlannedEngine[]): PlannedEngine[] {
  const maximum = Math.max(0, ...engines.map((engine) => money(engine.eurPerRun) ?? 0));
  return engines.map((engine) => ({ ...engine, eurPerRun: engine.eurPerRun === null ? null : Math.max(engine.eurPerRun, maximum) }));
}
