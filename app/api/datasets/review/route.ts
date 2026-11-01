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
    const examples = await supabaseRest("dataset_examples", { query: `select=id,status,manual_review_status,review_note,edited_prompt_text,validation_tier,persona,journey_stage,specificity_level,pre_execution_score,quality_score,stability_score,reproduction_score,expected_sub_intents,prompts!dataset_examples_prompt_id_fkey(id,text,provenance,confidence,clusters(label))&dataset_id=eq.${encodeURIComponent(datasetId)}&status=eq.accepted${filter}&order=quality_score.desc` });
    return NextResponse.json({ examples });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}

export async function PATCH(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.exampleId || !statuses.has(body.status)) return NextResponse.json({ error: "exampleId et status valide sont requis." }, { status: 400 });
  const editedText = typeof body.editedPromptText === "string" ? body.editedPromptText.trim() || null : null;
  const update: Record<string, unknown> = {
    manual_review_status: body.status,
    review_note: typeof body.note === "string" ? body.note.trim() || null : null,
    edited_prompt_text: editedText,
    reviewed_at: body.status === "pending" ? null : new Date().toISOString(),
  };
  try {
    if (editedText) {
      // An edited text is a new, unexecuted version: execution-derived scores
      // must not be presented as validating the new formulation.
      const current = await supabaseRest<Array<{ edited_prompt_text: string | null; prompts: { text: string } | { text: string }[] | null }>>("dataset_examples", { query: `select=edited_prompt_text,prompts!dataset_examples_prompt_id_fkey(text)&id=eq.${encodeURIComponent(body.exampleId)}&limit=1` });
      const row = current[0];
      const original = row?.edited_prompt_text || (Array.isArray(row?.prompts) ? row?.prompts[0]?.text : row?.prompts?.text) || "";
      if (editedText !== original) {
        Object.assign(update, { completed_runs: 0, stability_score: null, reproduction_score: null, quality_score: null });
      }
    }
    const examples = await supabaseRest("dataset_examples", { method: "PATCH", query: `id=eq.${encodeURIComponent(body.exampleId)}`, body: update });
    return NextResponse.json({ examples });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Mise à jour impossible." }, { status: 502 });
  }
}
