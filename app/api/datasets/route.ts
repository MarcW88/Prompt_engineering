import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, datasets: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const encoded = encodeURIComponent(projectId);
    const [datasets, geoClusters, projects] = await Promise.all([
      supabaseRest("datasets", { query: `select=*&project_id=eq.${encoded}&order=created_at.desc` }),
      supabaseRest("clusters", { query: `select=id&project_id=eq.${encoded}&is_geo_relevant=eq.true` }) as Promise<Array<{ id: string }>>,
      supabaseRest("projects", { query: `select=name,website&id=eq.${encoded}&limit=1` }) as Promise<Array<{ name: string; website: string | null }>>,
    ]);
    return NextResponse.json({ configured: true, datasets, geoClusters: geoClusters.length, projectName: projects[0]?.name ?? "", projectWebsite: projects[0]?.website ?? "" });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
