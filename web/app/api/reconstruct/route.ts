import { NextResponse } from "next/server";

function normalize(value: string) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body || !Array.isArray(body.fanOuts) || body.fanOuts.length === 0) {
    return NextResponse.json({ error: "fanOuts doit contenir au moins une requête." }, { status: 400 });
  }
  const fanOuts = [...new Map(body.fanOuts.filter((item: unknown) => typeof item === "string" && item.trim()).map((item: string) => [normalize(item), item.trim()])).values()].slice(0, 8);
  const language = typeof body.language === "string" ? body.language : "fr";
  const joined = fanOuts.slice(0, 4).join(", ");
  const templates: Record<string, string> = {
    fr: `Peux-tu m'aider à choisir en tenant compte de ces critères : ${joined} ?`,
    nl: `Kun je me helpen kiezen op basis van deze criteria: ${joined}?`,
    en: `Can you help me choose based on these criteria: ${joined}?`,
  };
  return NextResponse.json({
    prompt: templates[language] ?? templates.en,
    provenance: "reverse_engineered",
    confidence: 0.2,
    expectedFanOuts: fanOuts,
    method: "deterministic_fallback",
  });
}
