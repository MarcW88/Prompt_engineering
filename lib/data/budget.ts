export type BudgetStage = "collection" | "execution" | "validation" | "reverse_engineering" | "cloud" | "reserve";

export interface BudgetRecommendationInput {
  seeds: number;
  signals: number;
  themes: number;
  competitors: number;
  socialTargets: number;
  languages: number;
  markets: number;
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

export function recommendBudget(input: BudgetRecommendationInput): BudgetRecommendation {
  const score = Math.min(100,
    Math.min(30, input.seeds / 40) +
    Math.min(15, input.themes * 2) +
    Math.min(10, input.competitors * 1.5) +
    Math.min(15, input.socialTargets * 2) +
    Math.min(12, Math.max(0, input.languages - 1) * 6) +
    Math.min(10, Math.max(0, input.markets - 1) * 5) +
    Math.min(8, input.signals / 100)
  );
  const tier = score < 20 ? "light" : score < 45 ? "standard" : score < 70 ? "extended" : "segmented";
  const totalEur = { light: 4, standard: 8, extended: 12, segmented: 15 }[tier];
  const corpusTarget: [number, number] = {
    light: [100, 300], standard: [400, 1000], extended: [800, 2000], segmented: [1500, 4000],
  }[tier] as [number, number];
  const reasons = [
    `${input.seeds.toLocaleString("fr-FR")} seeds`,
    `${input.themes} thèmes`,
    `${Math.max(1, input.languages)} langue(s)`,
    `${input.socialTargets} cible(s) sociale(s)`,
  ];
  if (tier === "segmented") reasons.push("Périmètre complexe : segmentation recommandée avant extension");
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
