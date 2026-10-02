import { NextResponse } from "next/server";
import { createAndTriggerJob } from "@/lib/data/jobs";
import { confirmedCostEur } from "@/lib/data/budget";
import { supabaseRest } from "@/lib/data/supabase";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId || !body?.datasetId) return NextResponse.json({ error: "projectId et datasetId sont requis." }, { status: 400 });
  const targetRuns = Number(body.targetRuns);
  if (![3, 5].includes(targetRuns)) return NextResponse.json({ error: "targetRuns doit valoir 3 ou 5." }, { status: 400 });
  const limit = Math.max(1, Math.min(500, Number(body.limit ?? (targetRuns === 3 ? 100 : 50))));
  try {
    const encoded = encodeURIComponent(body.projectId);
    const [projects, costs, datasets] = await Promise.all([
      supabaseRest<Array<{ budget_total_eur: number }>>("projects", { query: `select=budget_total_eur&id=eq.${encoded}&limit=1` }),
      supabaseRest<Array<{ amount: number | null; currency: string; cost_status: string }>>("analysis_costs", { query: `select=amount,currency,cost_status&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ cost_per_execution_eur: number; repetitions: number; execution_sample_size: number }>>("datasets", { query: `select=cost_per_execution_eur,repetitions,execution_sample_size&id=eq.${encodeURIComponent(body.datasetId)}&limit=1` }),
    ]);
    const dataset = datasets[0];
    const additionalRuns = Math.max(0, targetRuns - Number(dataset?.repetitions ?? 1));
    const estimatedCostEur = Math.round(Math.min(limit, Number(dataset?.execution_sample_size ?? limit)) * additionalRuns * Number(dataset?.cost_per_execution_eur ?? 0) * 100) / 100;
    const totalBudgetEur = Number(projects[0]?.budget_total_eur ?? 8);
    const spentEur = confirmedCostEur(costs);
    if (spentEur + estimatedCostEur > totalBudgetEur) return NextResponse.json({ error: `Validation estimée à ${estimatedCostEur.toFixed(2)} € : budget global insuffisant (${spentEur.toFixed(2)} € / ${totalBudgetEur.toFixed(2)} € déjà confirmé).` }, { status: 422 });
    const result = await createAndTriggerJob({ project_id: body.projectId, kind: "validate_dataset", status: "pending", input: { dataset_id: body.datasetId, target_runs: targetRuns, limit, estimated_cost_eur: estimatedCostEur } });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création impossible." }, { status: 502 });
  }
}
