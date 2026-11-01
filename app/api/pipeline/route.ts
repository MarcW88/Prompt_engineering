import { NextResponse } from "next/server";
import { createAndTriggerJob } from "@/lib/data/jobs";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";
import { confirmedCostEur } from "@/lib/data/budget";

const stages = new Set(["prepare_questions", "transform_signals", "cluster_questions", "reverse_engineer"]);

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, jobs: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const jobs = await supabaseRest("jobs", { query: `select=id,kind,status,progress,output,error,created_at,completed_at&project_id=eq.${encodeURIComponent(projectId)}&kind=in.(transform_signals,cluster_questions,reverse_engineer)&order=created_at.desc&limit=20` });
    return NextResponse.json({ configured: true, jobs });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId || !stages.has(body.stage)) return NextResponse.json({ error: "projectId et stage valide sont requis." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, jobs: [] });
  let kind = body.stage;
  let input = body.input ?? {};
  if (body.stage === "prepare_questions") {
    kind = "transform_signals";
    input = { ...input, chain_cluster: true, cluster_config: { similarity_threshold: Number(body.similarityThreshold ?? 0.82), min_cluster_size: Number(body.minClusterSize ?? 2) } };
  }
  try {
    if (kind === "reverse_engineer") {
      if (!Array.isArray(input.target_observation_ids) || !input.target_observation_ids.length || !(Number(input.max_validation_executions) > 0)) {
        return NextResponse.json({ error: "Sélectionnez des target_observation_ids réels et un plafond max_validation_executions. Pour générer depuis les signaux utilisateurs, utilisez build_dataset." }, { status: 400 });
      }
      const encoded = encodeURIComponent(body.projectId);
      const [projects, costs, activeJobs] = await Promise.all([
        supabaseRest<Array<{ budget_total_eur: number }>>("projects", { query: `select=budget_total_eur&id=eq.${encoded}&limit=1` }),
        supabaseRest<Array<{ amount: number | null; currency: string; cost_status: string }>>("analysis_costs", { query: `select=amount,currency,cost_status&project_id=eq.${encoded}` }),
        supabaseRest<Array<{ input: Record<string, unknown> | null }>>("jobs", { query: `select=input&project_id=eq.${encoded}&status=in.(pending,running)` }),
      ]);
      const totalBudgetEur = Number(projects[0]?.budget_total_eur ?? 8);
      // Dépense engagée = coûts confirmés + réservations des jobs encore actifs.
      const concurrentReservedEur = activeJobs.reduce((sum, job) => sum + Number(job.input?.reserved_cost_eur ?? 0), 0);
      const spentEur = confirmedCostEur(costs) + concurrentReservedEur;
      const reserveEur = Math.max(0.25, Math.round(totalBudgetEur * 0.1 * 100) / 100);
      if (spentEur + reserveEur > totalBudgetEur) return NextResponse.json({ error: `Réserve reverse engineering insuffisante : ${reserveEur.toFixed(2)} € requis, ${Math.max(0, totalBudgetEur - spentEur).toFixed(2)} € restant.` }, { status: 422 });
      input = { ...input, reserved_cost_eur: reserveEur };
    }
    const result = await createAndTriggerJob({ project_id: body.projectId, kind, status: "pending", input });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création du job impossible." }, { status: 502 });
  }
}
