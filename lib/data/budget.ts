export type BudgetStage = "collection" | "execution" | "validation" | "reverse_engineering" | "cloud" | "reserve";

export interface BudgetRecommendationInput {
  seeds?: number;
  signals?: number;
  themes?: number;
  competitors?: number;
  socialTargets?: number;
  languages?: number;
  markets?: number;
  plannedRequests?: number;
  sources?: string[];
  socialPostLimit?: number;
  socialCommentLimit?: number;
  sampleMode?: boolean;
}

export interface BudgetRecommendation {
  tier: "light" | "standard" | "extended" | "segmented";
  score: number;
  totalEur: number;
  corpusTarget: [number, number];
  reasons: string[];
  allocations: Record<BudgetStage, number>;
}

const shares: Record<BudgetStage, number> = {
  collection: 0.3,
  execution: 0.28,
  validation: 0.17,
  reverse_engineering: 0.1,
  cloud: 0.05,
  reserve: 0.1,
};

const sourceWeights: Record<string, number> = {
  serp: 1,
  review: 1,
  forum: 2,
  reddit: 3,
  facebook: 4,
  instagram: 4,
  linkedin: 4,
  x: 4,
};

// Indicative cost per source in EUR for a small sample run. Used for pre-flight
// warnings only; real costs depend on provider billing.
const sourceCostHints: Record<string, number> = {
  serp: 0.05,
  review: 0.10,
  forum: 0.10,
  reddit: 0.30,
  facebook: 0.60,
  instagram: 0.60,
  linkedin: 0.60,
  x: 0.60,
};

export interface CostEstimateInput {
  sources: string[];
  plannedRequests: number;
  queryBudget: number;
  sampleMode: boolean;
  socialTargets: number;
  socialPostLimit: number;
  socialCommentLimit: number;
}

export interface TargetPromptConfig {
  targetPrompts: number;
  sampleMode: boolean;
  estimatedClusters: number;
  estimatedSignals: number;
  queryBudget: number;
  minimumSourceSignals: number;
  sources: string[];
  socialSources: string[];
  socialSharePercent: number;
  maxSocialTargets: number;
  collectionCostEur: number;
  totalBudgetEur: number;
}

export function estimateCollectionCostEur(input: CostEstimateInput): number {
  const sourceCount = Math.max(1, input.sources.length);
  const requestBudget = input.sampleMode ? Math.max(1, input.queryBudget) : Math.max(1, input.queryBudget) * sourceCount;
  let cost = 0;
  for (const source of input.sources) {
    const base = sourceCostHints[source] ?? 0.3;
    cost += base + (requestBudget / sourceCount) * (base / 10);
  }
  const socialSources = input.sources.filter((source) => ["reddit", "facebook", "instagram", "linkedin", "x"].includes(source));
  if (socialSources.length && input.socialTargets) {
    cost += socialSources.length * input.socialTargets * input.socialPostLimit * (1 + input.socialCommentLimit * 0.4) * 0.02;
  }
  return Math.round(cost * 100) / 100;
}

export function recommendConfigForTargetPrompts(targetPrompts: number, sampleMode = true): TargetPromptConfig {
  // Realistic funnel assumptions for an efficient GEO pipeline:
  // - 1 approved prompt needs ~4 generated candidates (validation/approval drop-off)
  // - 1 cluster generates up to 9 candidates by default (persona × stage × specificity)
  // - 1 cluster needs ~2-3 signals (questions)
  // - 1 signal needs ~1 external request
  const candidatesPerApprovedPrompt = 4;
  const candidatesPerCluster = 9;
  const signalsPerCluster = 2.5;
  const requestsPerSignal = 1.1;
  const estimatedCandidates = Math.ceil(targetPrompts * candidatesPerApprovedPrompt);
  const estimatedClusters = Math.ceil(estimatedCandidates / candidatesPerCluster);
  const estimatedSignals = Math.ceil(estimatedClusters * signalsPerCluster);
  const estimatedRequests = Math.ceil(estimatedSignals * requestsPerSignal);
  // Always include all social families, but keep their combined budget share
  // capped so they do not dominate the cost. The worker allocates a shared
  // social budget pool (max ~35%) split across the active social platforms.
  const coreSources = ["serp", "review", "forum"];
  const socialSources = ["reddit", "facebook", "instagram", "linkedin", "x"];
  const sources = [...coreSources, ...socialSources];
  const sourceCount = sources.length;
  // In sample mode the per-source budget is split across sources; in full audit
  // each active source receives the full query budget, so we keep it lower.
  const queryBudget = sampleMode
    ? Math.max(5, Math.min(50, Math.ceil(estimatedRequests / sourceCount / 2)))
    : Math.max(3, Math.min(25, Math.ceil(estimatedRequests / sourceCount / 3)));
  // Weighted cost per request: SERP/reviews/forums are cheap, social is more
  // expensive. In full audit the same budget applies to each source, but the
  // average cost is driven by the mix of sources chosen. The social pool cap in
  // the worker keeps social spend bounded even when all platforms are selected.
  // Use a weighted average assuming ~35% social budget share spread thinly.
  const averageCostPerRequest = 0.025;
  const fullAuditMultiplier = sampleMode ? 1 : 1.4;
  const collectionCostEur = Math.round(estimatedRequests * averageCostPerRequest * fullAuditMultiplier * 100) / 100;
  const totalBudgetEur = Math.min(30, Math.max(4, Math.round(collectionCostEur * 2.5)));
  // The worker caps the combined social budget pool at ~35% of the total query
  // budget when several social platforms are active.
  const socialSharePercent = Math.round(0.35 * 100);
  const maxSocialTargets = Math.max(socialSources.length, Math.ceil(queryBudget * 0.35));
  return {
    targetPrompts,
    sampleMode,
    estimatedClusters,
    estimatedSignals,
    queryBudget,
    minimumSourceSignals: Math.max(3, Math.min(20, Math.ceil(estimatedSignals / sourceCount / 2))),
    sources,
    socialSources,
    socialSharePercent,
    collectionCostEur,
    totalBudgetEur,
    maxSocialTargets,
  };
}

export function recommendBudget(input: BudgetRecommendationInput): BudgetRecommendation {
  const sources = input.sources ?? [];
  const sampleMode = input.sampleMode ?? true;
  const plannedRequests = Math.max(0, input.plannedRequests ?? 0);
  const socialTargets = input.socialTargets ?? 0;
  const socialPostLimit = Math.max(1, input.socialPostLimit ?? 10);
  const socialCommentLimit = Math.max(0, input.socialCommentLimit ?? 0);

  // The real cost drivers are the selected sources, the number of external calls
  // planned, and the social amplification (targets × posts × comments).
  // Seeds themselves do not increase cost: they are only stored locally until used
  // in templates or passed as inputs.
  const sourceScore = sources.reduce((sum, source) => sum + (sourceWeights[source] ?? 2), 0);
  // In sample mode the planned requests are split across sources, so the real
  // paid volume per source is much lower.
  const effectiveRequests = sampleMode && sources.length > 1 ? plannedRequests / sources.length : plannedRequests;
  const volumeScore = Math.min(40, effectiveRequests / 10);
  const socialAmplification = socialTargets * socialPostLimit * (1 + socialCommentLimit * 0.4);
  const socialScore = Math.min(35, socialAmplification / 8);
  const diversityScore = Math.min(15,
    Math.max(0, (input.languages ?? 1) - 1) * 4 +
    Math.max(0, (input.markets ?? 1) - 1) * 3 +
    Math.min(6, (input.themes ?? 0) * 1.5) +
    Math.min(5, (input.competitors ?? 0) * 1.5)
  );

  const score = Math.min(100, Math.round(sourceScore + volumeScore + socialScore + diversityScore));
  const tier = score < 15 ? "light" : score < 35 ? "standard" : score < 60 ? "extended" : "segmented";
  const totalEur = { light: 2, standard: 4, extended: 8, segmented: 12 }[tier];
  const corpusTarget: [number, number] = {
    light: [50, 200], standard: [150, 500], extended: [400, 1200], segmented: [800, 2500],
  }[tier] as [number, number];
  const reasons = [
    `${sources.length} source(s) sélectionnée(s)`,
    `${plannedRequests.toLocaleString("fr-FR")} planification(s) estimée(s)`,
  ];
  if (socialTargets) reasons.push(`${socialTargets} cible(s) sociale(s)`);
  if (socialCommentLimit) reasons.push(`${socialCommentLimit} commentaire(s) par post`);
  if ((input.languages ?? 1) > 1) reasons.push(`${input.languages} langues`);
  if ((input.markets ?? 1) > 1) reasons.push(`${input.markets} marchés`);
  if (tier === "segmented") reasons.push("Périmètre large : découper l’audit en plusieurs collectes");
  const allocations = Object.fromEntries(Object.entries(shares).map(([stage, share]) => [stage, Math.round(totalEur * share * 100) / 100])) as Record<BudgetStage, number>;
  return { tier, score: Math.round(score), totalEur, corpusTarget, reasons, allocations };
}

export function confirmedCostEur(rows: Array<{ amount?: unknown; currency?: unknown; cost_status?: unknown }>) {
  return Math.round(rows.reduce((sum, row) => {
    if (!["actual", "account_delta"].includes(String(row.cost_status)) || row.amount == null) return sum;
    const amount = Number(row.amount) || 0;
    return sum + (String(row.currency).toLowerCase() === "usd" ? amount * 0.92 : amount);
  }, 0) * 100) / 100;
}
