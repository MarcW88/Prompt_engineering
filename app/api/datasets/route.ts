import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, datasets: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const datasets = await supabaseRest("datasets", { query: `select=*&project_id=eq.${encodeURIComponent(projectId)}&order=created_at.desc` });
    return NextResponse.json({ configured: true, datasets });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
