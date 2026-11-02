import { NextResponse } from "next/server";
import { createReservedAndTriggerJob } from "@/lib/data/jobs";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

const allowedEngines = new Set(["chatgpt", "perplexity", "gemini", "google_ai_mode"]);

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, dataset: null });
  const candidatePoolSize = Math.max(1, Math.min(20000, Number(body.candidatePoolSize ?? body.targetSize ?? 2000)));
  const executionSampleSize = Math.max(1, Math.min(candidatePoolSize, Number(body.executionSampleSize ?? 100)));
  const repetitions = Math.max(1, Math.min(5, Number(body.repetitions ?? 1)));
  const candidatesPerCluster = Math.max(1, Math.min(36, Number(body.candidatesPerCluster ?? 9)));
  const engines = Array.isArray(body.engines) ? body.engines.filter((engine: unknown) => typeof engine === "string" && allowedEngines.has(engine)) : ["chatgpt"];
  if (!engines.length) return NextResponse.json({ error: "Sélectionnez au moins un moteur." }, { status: 400 });
  const costPerExecutionEur = Math.max(0, Number(body.costPerExecutionEur ?? 0));
  const maxBudgetEur = Math.max(0, Number(body.maxBudgetEur ?? 20));
  const estimatedCostEur = Math.round(executionSampleSize * repetitions * engines.length * costPerExecutionEur * 100) / 100;
  if (estimatedCostEur > maxBudgetEur) return NextResponse.json({ error: `Coût estimé ${estimatedCostEur.toFixed(2)} € supérieur au budget maximum ${maxBudgetEur.toFixed(2)} €. Augmentez le plafond ou réduisez les moteurs/l'échantillon.` }, { status: 422 });
  try {
    const encoded = encodeURIComponent(body.projectId);
    const clusters = await supabaseRest<Array<{ id: string }>>("clusters", { query: `select=id&project_id=eq.${encoded}&is_geo_relevant=eq.true` });
    if (!clusters.length) return NextResponse.json({ error: "Aucun cluster GEO exploitable. Lancez d'abord le clustering." }, { status: 409 });
    const datasets = await supabaseRest<Array<{ id: string }>>("datasets", { method: "POST", body: [{ project_id: body.projectId, name: body.name ?? `Dataset ${new Date().toLocaleDateString("fr-BE")}`, target_size: candidatePoolSize, candidate_pool_size: candidatePoolSize, execution_sample_size: executionSampleSize, repetitions, engines, cost_per_execution_eur: costPerExecutionEur, max_budget_eur: maxBudgetEur, estimated_cost_eur: estimatedCostEur, build_config: { candidates_per_cluster: candidatesPerCluster, max_per_cluster: Number(body.maxPerCluster ?? 5), personas: body.personas ?? [], stages: body.stages ?? ["discovery", "comparison"], specificity_levels: body.specificityLevels ?? [0, 1, 2], quality_threshold: Number(body.qualityThreshold ?? 0.65), mode: body.mode === "matrix" ? "matrix" : "faithful", fanout_fallback: body.fanoutFallback !== false, brand_name: String(body.brandName ?? "") } }] });
    const dataset = datasets[0];
    // Réservation atomique côté base : le solde est vérifié sous verrou au
    // moment de la création du job, ce qui écarte les dépassements concurrents.
    const result = await createReservedAndTriggerJob({ project_id: body.projectId, kind: "build_dataset", status: "pending", input: { dataset_id: dataset.id }, reserved_cost_eur: estimatedCostEur });
    return NextResponse.json({ dataset, ...result }, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Construction impossible.";
    if (message.includes("budget_exceeded")) return NextResponse.json({ error: "Budget global insuffisant pour cette étape (coûts confirmés + réservations des jobs actifs prises en compte)." }, { status: 422 });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
