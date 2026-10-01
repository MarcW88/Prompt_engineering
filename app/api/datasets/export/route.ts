import { NextResponse } from "next/server";
import { supabaseRest } from "@/lib/data/supabase";

function csv(value: unknown) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const datasetId = params.get("datasetId");
  const tier = Math.max(1, Math.min(3, Number(params.get("tier") ?? 3)));
  if (!datasetId) return NextResponse.json({ error: "datasetId est requis." }, { status: 400 });
  try {
    const examples = await supabaseRest<Array<Record<string, unknown>>>("dataset_examples", { query: `select=id,edited_prompt_text,validation_tier,persona,journey_stage,specificity_level,pre_execution_score,quality_score,stability_score,reproduction_score,prompts(text,provenance,confidence,clusters(label))&dataset_id=eq.${encodeURIComponent(datasetId)}&status=eq.accepted&manual_review_status=eq.approved&validation_tier=lte.${tier}&order=quality_score.desc` });
    const header = ["prompt", "category", "persona", "intent", "specificity", "provenance", "confidence_score", "pre_execution_score", "quality_score", "stability_score", "reproduction_score", "tier"];
    const rows = examples.map((example) => {
      const prompt = example.prompts as Record<string, unknown>;
      const cluster = prompt?.clusters as Record<string, unknown> | null;
      return [example.edited_prompt_text || prompt?.text, cluster?.label, example.persona, example.journey_stage, example.specificity_level, prompt?.provenance, prompt?.confidence, example.pre_execution_score, example.quality_score, example.stability_score, example.reproduction_score, example.validation_tier].map(csv).join(",");
    });
    return new NextResponse([header.join(","), ...rows].join("\n"), { headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": `attachment; filename="semactic-tier-${tier}.csv"` } });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Export impossible." }, { status: 502 });
  }
}
