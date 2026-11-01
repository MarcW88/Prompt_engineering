import { NextResponse } from "next/server";
import { createAndTriggerJob, createReservedAndTriggerJob } from "@/lib/data/jobs";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

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
      // Réserve proportionnée au plan déclaré : exécutions moteur plafonnées
      // + coût ICL/embeddings OpenAI par cible.
      const targetCount = Math.min(input.target_observation_ids.length, 10);
      const candidates = Math.max(3, Math.min(5, Number(input.max_candidates_per_cluster ?? 3)));
      const runs = Math.max(1, Math.min(4, Number(input.validation_runs ?? 1)));
      const costPerExecution = Math.max(0, Number(input.cost_per_execution_eur ?? 0.05));
      const plannedExecutions = Math.min(Number(input.max_validation_executions), targetCount * candidates * runs);
      const reserveEur = Math.round((plannedExecutions * costPerExecution + targetCount * 0.02) * 100) / 100;
      const result = await createReservedAndTriggerJob({ project_id: body.projectId, kind, status: "pending", input, reserved_cost_eur: reserveEur });
      return NextResponse.json(result, { status: 202 });
    }
    const result = await createAndTriggerJob({ project_id: body.projectId, kind, status: "pending", input });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Création du job impossible.";
    if (message.includes("budget_exceeded")) return NextResponse.json({ error: "Budget global insuffisant pour cette réserve (coûts confirmés + réservations des jobs actifs prises en compte)." }, { status: 422 });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
