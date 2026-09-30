import { NextResponse } from "next/server";
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
    const jobs = await supabaseRest("jobs", { method: "POST", body: [{ project_id: body.projectId, kind, status: "pending", input }] });
    return NextResponse.json({ jobs }, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création du job impossible." }, { status: 502 });
  }
}
