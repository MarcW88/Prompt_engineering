import { NextResponse } from "next/server";
import { confirmedCostEur, recommendBudget } from "@/lib/data/budget";
import { supabaseRest } from "@/lib/data/supabase";

function listLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function computePlannedRequests(jobInput: { sources?: string[]; query_budget?: number; source_config?: Record<string, unknown> } | undefined): number {
  const sources = jobInput?.sources ?? [];
  const queryBudget = Math.max(1, Math.floor(Number(jobInput?.query_budget ?? 10)));
  const sourceConfig = jobInput?.source_config ?? {};
  const counts = {
    reddit: listLength(sourceConfig.subreddits),
    forum: listLength(sourceConfig.forum_urls),
    facebook: listLength(sourceConfig.facebook_urls),
    instagram: listLength(sourceConfig.instagram_urls),
    linkedin: listLength(sourceConfig.linkedin_urls),
    x: listLength(sourceConfig.x_urls),
  };
  return (
    (sources.includes("reddit") ? queryBudget * Math.max(1, counts.reddit) : 0) +
    (sources.includes("forum") ? queryBudget * Math.max(1, counts.forum) : 0) +
    (sources.includes("serp") ? queryBudget : 0) +
    (sources.includes("facebook") ? queryBudget * Math.max(1, counts.facebook) : 0) +
    (sources.includes("instagram") ? queryBudget * Math.max(1, counts.instagram) : 0) +
    (sources.includes("linkedin") ? queryBudget * Math.max(1, counts.linkedin) : 0) +
    (sources.includes("x") ? queryBudget * Math.max(1, counts.x) : 0) +
    (sources.includes("review") ? Math.min(10, queryBudget) : 0)
  );
}

export async function GET(request: Request) {
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const encoded = encodeURIComponent(projectId);
    const [projects, seeds, signals, costs, jobs] = await Promise.all([
      supabaseRest<Array<{ id: string; budget_total_eur: number; budget_profile: Record<string, unknown> }>>("projects", { query: `select=id,budget_total_eur,budget_profile&id=eq.${encoded}&limit=1` }),
      supabaseRest<Array<{ id: string }>>("seeds", { query: `select=id&project_id=eq.${encoded}&enabled=eq.true` }),
      supabaseRest<Array<{ id: string }>>("signals", { query: `select=id&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ amount: number | null; currency: string; cost_status: string }>>("analysis_costs", { query: `select=amount,currency,cost_status&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ input?: { sources?: string[]; query_budget?: number; source_config?: Record<string, unknown> } }>>("jobs", { query: `select=input&project_id=eq.${encoded}&kind=eq.collect_sources&order=created_at.desc&limit=1` }),
    ]);
    if (!projects[0]) return NextResponse.json({ error: "Workspace introuvable." }, { status: 404 });
    const source = jobs[0]?.input?.source_config ?? {};
    const plannedRequests = computePlannedRequests(jobs[0]?.input ?? {});
    const recommendation = recommendBudget({
      seeds: seeds.length,
      signals: signals.length,
      themes: listLength(source.themes),
      competitors: listLength(source.competitors),
      socialTargets: ["subreddits", "facebook_urls", "instagram_urls", "linkedin_urls", "x_urls"].reduce((sum, key) => sum + listLength(source[key]), 0),
      languages: Math.max(1, listLength(source.languages)),
      markets: 1,
      plannedRequests,
      sources: jobs[0]?.input?.sources ?? [],
      socialPostLimit: Number(source.social_post_limit ?? 10),
      socialCommentLimit: Number(source.social_comment_limit ?? 0),
    });
    const configuredTotal = Number(projects[0].budget_total_eur || recommendation.totalEur);
    const confirmedEur = confirmedCostEur(costs);
    return NextResponse.json({
      configuredTotal,
      confirmedEur,
      remainingEur: Math.max(0, Math.round((configuredTotal - confirmedEur) * 100) / 100),
      spentPercent: configuredTotal ? Math.min(100, Math.round(confirmedEur / configuredTotal * 100)) : 0,
      recommendation,
      profile: projects[0].budget_profile ?? {},
    });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Budget indisponible." }, { status: 502 });
  }
}

export async function PATCH(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  const total = Math.max(1, Math.min(30, Number(body.totalEur ?? 8)));
  try {
    const rows = await supabaseRest("projects", { method: "PATCH", query: `id=eq.${encodeURIComponent(body.projectId)}`, body: { budget_total_eur: total, budget_profile: body.profile ?? {} } });
    return NextResponse.json({ project: Array.isArray(rows) ? rows[0] : rows, totalEur: total });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Mise à jour impossible." }, { status: 502 });
  }
}
