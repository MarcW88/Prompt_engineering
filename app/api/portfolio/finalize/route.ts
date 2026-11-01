import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

// §16.1.8 — "finaliser" freezes a portfolio version: method, exact texts and
// associated results. Persisted as a completed `jobs` row (kind=
// portfolio_finalization) so no schema change is required; later executions
// and edits create a new traceable state, they never rewrite the snapshot.

type Row = Record<string, unknown>;

export async function POST(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ error: "Supabase n'est pas configuré." }, { status: 503 });
  const body = await request.json().catch(() => ({}));
  const projectId = String(body.projectId ?? "");
  const label = String(body.label ?? "");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });

  try {
    const project = encodeURIComponent(projectId);
    const datasets = await supabaseRest<Array<{ id: string }>>("datasets", { query: `select=id&project_id=eq.${project}` });
    const datasetIds = datasets.map((row) => row.id);
    const examples = datasetIds.length
      ? await supabaseRest<Row[]>("dataset_examples", { query: `select=id,prompt_id,status,manual_review_status,edited_prompt_text,quality_score,stability_score,reproduction_score,completed_runs&dataset_id=in.(${datasetIds.join(",")})` })
      : [];
    const approved = examples.filter((row) => row.manual_review_status === "approved");
    if (!approved.length) return NextResponse.json({ error: "Aucun prompt approuvé à figer." }, { status: 409 });
    const promptIds = [...new Set(approved.map((row) => String(row.prompt_id)))];
    const prompts = await supabaseRest<Row[]>("prompts", { query: `select=id,text&project_id=eq.${project}&id=in.(${promptIds.join(",")})` });
    const promptById = new Map(prompts.map((row) => [String(row.id), row]));

    const versionId = `fin-${new Date().toISOString().replace(/[:.]/g, "").slice(0, 15)}`;
    const snapshot = {
      version_id: versionId,
      label,
      finalized_at: new Date().toISOString(),
      method_version: "v1.0-2026-11-01",
      code_sha: process.env.VERCEL_GIT_COMMIT_SHA || "local-dev",
      prompt_version_ids: approved.map((row) => String(row.id)),
      versions: approved.map((row) => ({
        prompt_version_id: row.id,
        prompt_id: row.prompt_id,
        text: String(row.edited_prompt_text || promptById.get(String(row.prompt_id))?.text || ""),
        quality_score: row.quality_score ?? null,
        reproduction_score: row.reproduction_score ?? null,
        completed_runs: row.completed_runs ?? 0,
      })),
    };
    const rows = await supabaseRest<Row[]>("jobs", {
      method: "POST",
      body: [{ project_id: projectId, kind: "portfolio_finalization", status: "completed", input: { label }, output: snapshot, completed_at: new Date().toISOString() }],
    });
    return NextResponse.json({ version_id: versionId, job_id: rows[0]?.id, frozen_versions: approved.length });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Finalisation impossible." }, { status: 502 });
  }
}
