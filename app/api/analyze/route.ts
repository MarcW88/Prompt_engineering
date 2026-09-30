import { randomUUID } from "crypto";
import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

type AnalyzeBody = { prompt?: string; provider?: string; engine?: string; country?: string; language?: string; projectId?: string };
type RunBody = Required<Omit<AnalyzeBody, "projectId">>;

const brightDataIds: Record<string, string | undefined> = {
  chatgpt: process.env.BRIGHTDATA_CHATGPT_DATASET_ID,
  perplexity: process.env.BRIGHTDATA_PERPLEXITY_DATASET_ID,
  gemini: process.env.BRIGHTDATA_GEMINI_DATASET_ID,
  google_ai_mode: process.env.BRIGHTDATA_GOOGLE_AI_MODE_DATASET_ID,
};

const engineUrls: Record<string, string> = {
  chatgpt: "https://chatgpt.com/",
  perplexity: "https://www.perplexity.ai/",
  gemini: "https://gemini.google.com/",
  google_ai_mode: "https://www.google.com/",
};

function list(value: unknown, keys: string[]) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return item;
    if (item && typeof item === "object") {
      const record = item as Record<string, unknown>;
      for (const key of keys) if (typeof record[key] === "string") return record[key] as string;
    }
    return "";
  }).filter(Boolean);
}

function normalize(prompt: string, provider: string, engine: string, record: Record<string, unknown>) {
  const answer = ["answer", "response", "content", "text"].map((key) => record[key]).find((value) => typeof value === "string") ?? "";
  const fanOutValue = ["query_fan_out", "query_fan_outs", "search_queries", "queries"].map((key) => record[key]).find(Array.isArray);
  const citationValue = ["citations", "sources", "links", "references"].map((key) => record[key]).find(Array.isArray);
  return {
    id: randomUUID(), prompt, provider, engine, answer,
    fanOuts: list(fanOutValue, ["query", "text", "title", "keyword"]),
    citations: Array.isArray(citationValue) ? citationValue : [],
    model: record.model ?? record.model_name ?? record.version ?? "",
    webSearchTriggered: record.web_search_triggered ?? null,
    timestamp: new Date().toISOString(), raw: record,
  };
}

async function brightData(body: RunBody) {
  const token = process.env.BRIGHTDATA_API_KEY;
  const datasetId = brightDataIds[body.engine];
  if (!token || !datasetId) throw new Error(`Bright Data n'est pas configuré pour ${body.engine}.`);
  const response = await fetch(`https://api.brightdata.com/datasets/v3/scrape?dataset_id=${encodeURIComponent(datasetId)}&format=json&include_errors=true`, {
    method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify([{ url: engineUrls[body.engine] ?? engineUrls.chatgpt, prompt: body.prompt, country: body.country.toLowerCase(), language: body.language, web_search: true }]),
  });
  if (!response.ok) throw new Error(`Bright Data HTTP ${response.status}`);
  const raw = await response.json();
  const record = Array.isArray(raw) ? raw[0] : raw;
  return normalize(body.prompt, body.provider, body.engine, record);
}

async function oxylabs(body: RunBody) {
  const username = process.env.OXYLABS_USERNAME;
  const password = process.env.OXYLABS_PASSWORD;
  if (!username || !password) throw new Error("Oxylabs n'est pas configuré.");
  const sources: Record<string, string> = { chatgpt: "chatgpt", perplexity: "perplexity", google_ai_mode: "google_ai_mode" };
  if (!sources[body.engine]) throw new Error(`Oxylabs ne prend pas en charge ${body.engine}.`);
  const response = await fetch("https://realtime.oxylabs.io/v1/queries", {
    method: "POST", headers: { Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`, "Content-Type": "application/json" },
    body: JSON.stringify({ source: sources[body.engine], query: body.prompt, geo_location: body.country, locale: body.language, parse: true }),
  });
  if (!response.ok) throw new Error(`Oxylabs HTTP ${response.status}`);
  const raw = await response.json();
  const outer = Array.isArray(raw.results) ? raw.results[0] : raw;
  const record = outer && typeof outer.content === "object" ? outer.content : outer;
  return normalize(body.prompt, body.provider, body.engine, record);
}

async function persist(projectId: string, result: ReturnType<typeof normalize>, body: RunBody) {
  if (!isSupabaseConfigured()) return;
  const prompts = await supabaseRest<Array<{ id: string }>>("prompts", { method: "POST", body: [{ project_id: projectId, text: result.prompt, provenance: "observed", confidence: 1, status: "testing", expected_fan_outs: result.fanOuts }] });
  const promptId = prompts[0]?.id;
  if (!promptId) return;
  const observations = await supabaseRest<Array<{ id: string }>>("observations", { method: "POST", body: [{ prompt_id: promptId, provider: body.provider, engine: body.engine, model: String(result.model), country: body.country, language: body.language, answer: String(result.answer), web_search_triggered: result.webSearchTriggered, raw_response: result.raw }] });
  const observationId = observations[0]?.id;
  if (!observationId) return;
  if (result.fanOuts.length) await supabaseRest("fan_outs", { method: "POST", body: result.fanOuts.map((query, index) => ({ observation_id: observationId, position: index + 1, query, normalized_query: query.toLowerCase().replace(/[^a-z0-9à-ÿ]+/g, " ").trim() })) });
  const citations = result.citations.flatMap((citation, index) => {
    if (typeof citation === "string") return [{ observation_id: observationId, position: index + 1, url: citation }];
    if (!citation || typeof citation !== "object") return [];
    const value = citation as Record<string, unknown>;
    const url = value.url ?? value.link ?? value.href;
    return typeof url === "string" ? [{ observation_id: observationId, position: index + 1, url, title: typeof value.title === "string" ? value.title : null }] : [];
  });
  if (citations.length) await supabaseRest("citations", { method: "POST", body: citations });
}

export async function POST(request: Request) {
  const input = await request.json().catch(() => null) as AnalyzeBody | null;
  if (!input?.prompt?.trim()) return NextResponse.json({ error: "Le prompt est requis." }, { status: 400 });
  const body: RunBody = { prompt: input.prompt.trim(), provider: input.provider ?? "brightdata", engine: input.engine ?? "chatgpt", country: input.country ?? "FR", language: input.language ?? "fr" };
  if (!engineUrls[body.engine]) return NextResponse.json({ error: "Moteur non pris en charge." }, { status: 400 });
  try {
    const result = body.provider === "oxylabs" ? await oxylabs(body) : await brightData(body);
    if (input.projectId) await persist(input.projectId, result, body);
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Analyse impossible." }, { status: 502 });
  }
}
