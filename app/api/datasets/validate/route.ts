import { NextResponse } from "next/server";
import { createReservedAndTriggerJob } from "@/lib/data/jobs";
import { supabaseRest } from "@/lib/data/supabase";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId || !body?.datasetId) return NextResponse.json({ error: "projectId et datasetId sont requis." }, { status: 400 });
  const targetRuns = Number(body.targetRuns);
  if (![3, 5].includes(targetRuns)) return NextResponse.json({ error: "targetRuns doit valoir 3 ou 5." }, { status: 400 });
  const limit = Math.max(1, Math.min(500, Number(body.limit ?? (targetRuns === 3 ? 100 : 50))));
  try {
    const datasets = await supabaseRest<Array<{ cost_per_execution_eur: number; repetitions: number; execution_sample_size: number; engines: string[] }>>("datasets", { query: `select=cost_per_execution_eur,repetitions,execution_sample_size,engines&id=eq.${encodeURIComponent(body.datasetId)}&limit=1` });
    const dataset = datasets[0];
    const additionalRuns = Math.max(0, targetRuns - Number(dataset?.repetitions ?? 1));
    const engineCount = Math.max(1, Array.isArray(dataset?.engines) ? dataset.engines.length : 1);
    const estimatedCostEur = Math.round(Math.min(limit, Number(dataset?.execution_sample_size ?? limit)) * additionalRuns * engineCount * Number(dataset?.cost_per_execution_eur ?? 0) * 100) / 100;
    // Réservation atomique : le solde (confirmé + réservations actives) est
    // vérifié sous verrou dans la même transaction que la création du job.
    const result = await createReservedAndTriggerJob({ project_id: body.projectId, kind: "validate_dataset", status: "pending", input: { dataset_id: body.datasetId, target_runs: targetRuns, limit, estimated_cost_eur: estimatedCostEur }, reserved_cost_eur: estimatedCostEur });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Création impossible.";
    if (message.includes("budget_exceeded")) return NextResponse.json({ error: `Budget global insuffisant : ${message.split("budget_exceeded:")[1] ?? "réserve non couverte"}` }, { status: 422 });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
