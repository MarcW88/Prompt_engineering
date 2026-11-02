import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, datasets: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const encoded = encodeURIComponent(projectId);
    const [datasets, geoClusters] = await Promise.all([
      supabaseRest("datasets", { query: `select=*&project_id=eq.${encoded}&order=created_at.desc` }),
      supabaseRest("clusters", { query: `select=id&project_id=eq.${encoded}&is_geo_relevant=eq.true` }) as Promise<Array<{ id: string }>>,
    ]);
    return NextResponse.json({ configured: true, datasets, geoClusters: geoClusters.length });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
