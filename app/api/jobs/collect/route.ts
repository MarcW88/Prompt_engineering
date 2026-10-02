import { NextResponse } from "next/server";
import { createAndTriggerJob } from "@/lib/data/jobs";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

const allowedSources = new Set(["reddit", "forum", "serp", "review", "facebook", "instagram", "linkedin"]);

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  const sources = Array.isArray(body.sources) ? body.sources.filter((source: unknown) => typeof source === "string" && allowedSources.has(source)) : [];
  if (!sources.length) return NextResponse.json({ error: "Sélectionnez au moins une source." }, { status: 400 });
  const queryBudget = Math.max(1, Math.min(200, Math.floor(Number(body.queryBudget ?? 10))));
  const sourceConfig = body.sourceConfig && typeof body.sourceConfig === "object" ? body.sourceConfig : {};
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, job: null, plannedSources: sources });
  try {
    const [seeds, activeJobs] = await Promise.all([
      supabaseRest<Array<{ id: string }>>("seeds", { query: `select=id&project_id=eq.${encodeURIComponent(body.projectId)}&enabled=eq.true&order=priority.desc` }),
      supabaseRest<Array<{ id: string }>>("jobs", { query: `select=id&project_id=eq.${encodeURIComponent(body.projectId)}&kind=eq.collect_sources&status=in.(pending,running)&limit=1` }),
    ]);
    if (!seeds.length) return NextResponse.json({ error: "Ajoutez au moins un seed actif avant de lancer la collecte." }, { status: 409 });
    if (activeJobs.length) return NextResponse.json({ error: "Une collecte est déjà en cours dans ce workspace.", jobId: activeJobs[0].id }, { status: 409 });
    const result = await createAndTriggerJob({ project_id: body.projectId, kind: "collect_sources", status: "pending", input: { sources, query_budget: queryBudget, source_config: sourceConfig } });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création du job impossible." }, { status: 502 });
  }
}
