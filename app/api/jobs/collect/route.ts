import { NextResponse } from "next/server";
import { createAndTriggerJob } from "@/lib/data/jobs";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";
import { confirmedCostEur } from "@/lib/data/budget";

const allowedSources = new Set(["reddit", "forum", "serp", "review", "facebook", "instagram", "linkedin", "x"]);

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  const sources = Array.isArray(body.sources) ? body.sources.filter((source: unknown) => typeof source === "string" && allowedSources.has(source)) : [];
  if (!sources.length) return NextResponse.json({ error: "Sélectionnez au moins une source." }, { status: 400 });
  const queryBudget = Math.max(1, Math.min(200, Math.floor(Number(body.queryBudget ?? 10))));
  const sourceConfig = body.sourceConfig && typeof body.sourceConfig === "object" ? body.sourceConfig : {};
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, job: null, plannedSources: sources });
  try {
    const [seeds, activeJobs, projects, costs] = await Promise.all([
      supabaseRest<Array<{ id: string }>>("seeds", { query: `select=id&project_id=eq.${encodeURIComponent(body.projectId)}&enabled=eq.true&order=priority.desc` }),
      supabaseRest<Array<{ id: string }>>("jobs", { query: `select=id&project_id=eq.${encodeURIComponent(body.projectId)}&kind=eq.collect_sources&status=in.(pending,running)&limit=1` }),
      supabaseRest<Array<{ budget_total_eur: number; budget_profile: Record<string, unknown> }>>("projects", { query: `select=budget_total_eur,budget_profile&id=eq.${encodeURIComponent(body.projectId)}&limit=1` }),
      supabaseRest<Array<{ amount: number | null; currency: string; cost_status: string }>>("analysis_costs", { query: `select=amount,currency,cost_status&project_id=eq.${encodeURIComponent(body.projectId)}` }),
    ]);
    if (!seeds.length) return NextResponse.json({ error: "Ajoutez au moins un seed actif avant de lancer la collecte." }, { status: 409 });
    if (activeJobs.length) return NextResponse.json({ error: "Une collecte est déjà en cours dans ce workspace.", jobId: activeJobs[0].id }, { status: 409 });
    const existingProfile = projects[0]?.budget_profile ?? {};
    const automaticBudget = Object.keys(existingProfile).length === 0;
    const recommendedBudget = Math.max(1, Math.min(30, Number((sourceConfig as Record<string, unknown>).recommended_budget_total_eur ?? 8)));
    const totalBudgetEur = automaticBudget ? recommendedBudget : Number(projects[0]?.budget_total_eur ?? 8);
    if (automaticBudget) await supabaseRest("projects", { method: "PATCH", query: `id=eq.${encodeURIComponent(body.projectId)}`, body: { budget_total_eur: totalBudgetEur, budget_profile: { ...((sourceConfig as Record<string, unknown>).budget_profile as Record<string, unknown> ?? {}), mode: "automatic" } } });
    const spentEur = confirmedCostEur(costs);
    if (spentEur >= totalBudgetEur) return NextResponse.json({ error: `Budget global atteint (${spentEur.toFixed(2)} € / ${totalBudgetEur.toFixed(2)} €). Augmentez le plafond ou segmentez l’audit.` }, { status: 422 });
    const result = await createAndTriggerJob({ project_id: body.projectId, kind: "collect_sources", status: "pending", input: { sources, query_budget: queryBudget, source_config: sourceConfig, budget_snapshot: { total_eur: totalBudgetEur, spent_eur: spentEur, remaining_eur: Math.max(0, totalBudgetEur - spentEur) } } });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création du job impossible." }, { status: 502 });
  }
}
