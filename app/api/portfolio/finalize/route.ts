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
    const prompts = await supabaseRest<Row[]>("prompts", { query: `select=id,cluster_id,text,provenance,metadata&project_id=eq.${project}&id=in.(${promptIds.join(",")})` });
    const promptById = new Map(prompts.map((row) => [String(row.id), row]));
    // Executed state at freeze time: a version counts as executed only if a
    // run has actually executed its exact text.
    const observations = promptIds.length
      ? await supabaseRest<Row[]>("observations", { query: `select=prompt_id,provider,engine,answer,executed_text:raw_response->>executed_text,error:raw_response->>error&prompt_id=in.(${promptIds.join(",")})` })
      : [];
    const runsByPromptText = new Map<string, { runs: number; surfaces: Set<string> }>();
    for (const obs of observations) {
      const key = `${obs.prompt_id}|${String(obs.executed_text || promptById.get(String(obs.prompt_id))?.text || "")}`;
      if (!String(obs.answer ?? "").trim() || obs.error) continue;
      const entry = runsByPromptText.get(key) ?? { runs: 0, surfaces: new Set<string>() };
      entry.runs += 1;
      entry.surfaces.add(`${obs.provider}/${obs.engine}`);
      runsByPromptText.set(key, entry);
    }

    const versionId = `fin-${new Date().toISOString().replace(/[:.]/g, "").slice(0, 15)}`;
    const snapshot = {
      version_id: versionId,
      label,
      finalized_at: new Date().toISOString(),
      method_version: "v1.0-2026-11-01",
      code_sha: process.env.VERCEL_GIT_COMMIT_SHA || "local-dev",
      prompt_version_ids: approved.map((row) => String(row.id)),
      versions: approved.map((row) => {
        const prompt = promptById.get(String(row.prompt_id));
        const meta = (prompt?.metadata ?? {}) as Row;
        const text = String(row.edited_prompt_text || prompt?.text || "");
        const executed = runsByPromptText.get(`${row.prompt_id}|${text}`) ?? { runs: 0, surfaces: new Set<string>() };
        return {
          prompt_version_id: row.id,
          prompt_id: row.prompt_id,
          cluster_id: prompt?.cluster_id ?? null,
          intent_id: String(meta.intent_id ?? ""),
          provenance: prompt?.provenance ?? "",
          origin: String(meta.method ?? prompt?.provenance ?? ""),
          text,
          selection_status: row.status,
          approval: row.manual_review_status,
          quality_score: row.quality_score ?? null,
          stability_score: row.stability_score ?? null,
          reproduction_score: row.reproduction_score ?? null,
          completed_runs: row.completed_runs ?? 0,
          executed_runs: executed.runs,
          surfaces_tested: [...executed.surfaces],
          executed_state: executed.runs ? "exécutée" : "approuvée non exécutée",
        };
      }),
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
