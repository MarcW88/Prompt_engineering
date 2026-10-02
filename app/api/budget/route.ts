import { NextResponse } from "next/server";
import { confirmedCostEur, recommendBudget } from "@/lib/data/budget";
import { supabaseRest } from "@/lib/data/supabase";

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
      supabaseRest<Array<{ input: { source_config?: Record<string, unknown> } }>>("jobs", { query: `select=input&project_id=eq.${encoded}&kind=eq.collect_sources&order=created_at.desc&limit=1` }),
    ]);
    if (!projects[0]) return NextResponse.json({ error: "Workspace introuvable." }, { status: 404 });
    const source = jobs[0]?.input?.source_config ?? {};
    const listLength = (key: string) => Array.isArray(source[key]) ? (source[key] as unknown[]).length : 0;
    const recommendation = recommendBudget({
      seeds: seeds.length,
      signals: signals.length,
      themes: listLength("themes"),
      competitors: listLength("competitors"),
      socialTargets: ["subreddits", "facebook_urls", "instagram_urls", "linkedin_urls", "x_urls"].reduce((sum, key) => sum + listLength(key), 0),
      languages: Math.max(1, listLength("languages")),
      markets: 1,
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
