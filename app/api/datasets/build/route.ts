import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

const allowedEngines = new Set(["chatgpt", "perplexity", "gemini", "google_ai_mode"]);

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, dataset: null });
  const targetSize = Math.max(1, Math.min(20000, Number(body.targetSize ?? 600)));
  const repetitions = Math.max(1, Math.min(10, Number(body.repetitions ?? 3)));
  const candidatesPerCluster = Math.max(1, Math.min(36, Number(body.candidatesPerCluster ?? 9)));
  const engines = Array.isArray(body.engines) ? body.engines.filter((engine: unknown) => typeof engine === "string" && allowedEngines.has(engine)) : ["chatgpt"];
  if (!engines.length) return NextResponse.json({ error: "Sélectionnez au moins un moteur." }, { status: 400 });
  try {
    const clusters = await supabaseRest<Array<{ id: string }>>("clusters", { query: `select=id&project_id=eq.${encodeURIComponent(body.projectId)}&is_geo_relevant=eq.true` });
    if (!clusters.length) return NextResponse.json({ error: "Aucun cluster GEO exploitable. Lancez d'abord le clustering." }, { status: 409 });
    const datasets = await supabaseRest<Array<{ id: string }>>("datasets", { method: "POST", body: [{ project_id: body.projectId, name: body.name ?? `Dataset ${new Date().toLocaleDateString("fr-BE")}`, target_size: targetSize, repetitions, engines, build_config: { candidates_per_cluster: candidatesPerCluster, personas: body.personas ?? [], stages: body.stages ?? ["discovery", "comparison"], specificity_levels: body.specificityLevels ?? [0, 1, 2], quality_threshold: Number(body.qualityThreshold ?? 0.65) } }] });
    const dataset = datasets[0];
    const jobs = await supabaseRest("jobs", { method: "POST", body: [{ project_id: body.projectId, kind: "build_dataset", status: "pending", input: { dataset_id: dataset.id } }] });
    return NextResponse.json({ dataset, jobs }, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Construction impossible." }, { status: 502 });
  }
}
