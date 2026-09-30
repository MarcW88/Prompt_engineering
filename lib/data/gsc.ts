export interface GscSignal {
  raw_text: string;
  title: string;
  metadata: { word_count: number; clicks: number; impressions: number };
}

function splitCsvLine(line: string, delimiter: string) {
  const values = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index++) {
    const character = line[index];
    if (character === '"' && line[index + 1] === '"' && quoted) { value += '"'; index++; }
    else if (character === '"') quoted = !quoted;
    else if (character === delimiter && !quoted) { values.push(value.trim()); value = ""; }
    else value += character;
  }
  values.push(value.trim());
  return values;
}

function number(value: string | undefined) {
  const parsed = Number((value ?? "0").replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(parsed) ? Math.round(parsed) : 0;
}

export function parseGscCsv(text: string, minWords = 10): GscSignal[] {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];
  const first = lines[0];
  const delimiter = [",", ";", "\t"].sort((left, right) => first.split(right).length - first.split(left).length)[0];
  const headers = splitCsvLine(first, delimiter);
  const normalized = headers.map((header) => header.toLowerCase().trim());
  const queryNames = ["top queries", "query", "queries", "search query", "requête", "requêtes"];
  const queryIndex = normalized.findIndex((header) => queryNames.includes(header));
  const clicksIndex = normalized.findIndex((header) => ["clicks", "clics"].includes(header));
  const impressionsIndex = normalized.indexOf("impressions");
  const seen = new Set<string>();
  return lines.slice(1).flatMap((line) => {
    const values = splitCsvLine(line, delimiter);
    const query = (values[queryIndex >= 0 ? queryIndex : 0] ?? "").trim();
    const key = query.toLowerCase().replace(/\s+/g, " ");
    const wordCount = query.split(/\s+/).filter(Boolean).length;
    if (!key || seen.has(key) || wordCount < minWords) return [];
    seen.add(key);
    return [{ raw_text: query, title: query, metadata: { word_count: wordCount, clicks: number(values[clicksIndex]), impressions: number(values[impressionsIndex]) } }];
  });
}
