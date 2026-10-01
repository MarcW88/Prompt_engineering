import { NextResponse } from "next/server";
import { supabaseRest } from "@/lib/data/supabase";

const statuses = new Set(["pending", "approved", "rejected"]);

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const datasetId = params.get("datasetId");
  const status = params.get("status");
  if (!datasetId) return NextResponse.json({ error: "datasetId est requis." }, { status: 400 });
  const filter = status && statuses.has(status) ? `&manual_review_status=eq.${status}` : "";
  try {
    const examples = await supabaseRest("dataset_examples", { query: `select=id,status,manual_review_status,review_note,edited_prompt_text,validation_tier,persona,journey_stage,specificity_level,pre_execution_score,quality_score,stability_score,reproduction_score,expected_sub_intents,prompts(id,text,provenance,confidence,clusters(label))&dataset_id=eq.${encodeURIComponent(datasetId)}&status=eq.accepted${filter}&order=quality_score.desc` });
    return NextResponse.json({ examples });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}

export async function PATCH(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.exampleId || !statuses.has(body.status)) return NextResponse.json({ error: "exampleId et status valide sont requis." }, { status: 400 });
  const update: Record<string, unknown> = {
    manual_review_status: body.status,
    review_note: typeof body.note === "string" ? body.note.trim() || null : null,
    edited_prompt_text: typeof body.editedPromptText === "string" ? body.editedPromptText.trim() || null : null,
    reviewed_at: body.status === "pending" ? null : new Date().toISOString(),
  };
  try {
    const examples = await supabaseRest("dataset_examples", { method: "PATCH", query: `id=eq.${encodeURIComponent(body.exampleId)}`, body: update });
    return NextResponse.json({ examples });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Mise à jour impossible." }, { status: 502 });
  }
}
