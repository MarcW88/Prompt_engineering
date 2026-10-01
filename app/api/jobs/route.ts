import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, jobs: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const jobs = await supabaseRest("jobs", {
      query: `select=id,kind,status,progress,input,output,error,created_at,started_at,completed_at,heartbeat_at,cloud_execution_id&project_id=eq.${encodeURIComponent(projectId)}&hidden_at=is.null&order=created_at.desc&limit=50`,
    });
    return NextResponse.json({ configured: true, jobs });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
