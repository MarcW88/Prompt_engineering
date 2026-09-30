export type SeedType = "keyword" | "theme" | "brand" | "competitor" | "product" | "problem";

export interface SeedInput {
  value: string;
  seedType: SeedType;
  priority: number;
  language: string;
  market: string;
  source: string;
  enabled: boolean;
}

export function parseSeedText(text: string, defaults: Partial<SeedInput> = {}): SeedInput[] {
  const seen = new Set<string>();
  return text.split(/[\n;,\t]+/).flatMap((entry) => {
    const value = entry.trim();
    const key = value.toLowerCase();
    if (!value || seen.has(key)) return [];
    seen.add(key);
    return [{ value, seedType: defaults.seedType ?? "keyword", priority: defaults.priority ?? 70, language: defaults.language ?? "fr", market: defaults.market ?? "BE", source: defaults.source ?? "manual", enabled: defaults.enabled ?? true }];
  });
}
