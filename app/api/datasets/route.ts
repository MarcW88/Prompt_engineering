import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, datasets: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const encoded = encodeURIComponent(projectId);
    const [datasets, geoClusters, projects, questions] = await Promise.all([
      supabaseRest("datasets", { query: `select=*&project_id=eq.${encoded}&order=created_at.desc` }),
      supabaseRest("clusters", { query: `select=id&project_id=eq.${encoded}&is_geo_relevant=eq.true` }) as Promise<Array<{ id: string }>>,
      supabaseRest("projects", { query: `select=name,website&id=eq.${encoded}&limit=1` }) as Promise<Array<{ name: string; website: string | null }>>,
      supabaseRest("questions", { query: `select=provenance,metadata&project_id=eq.${encoded}` }) as Promise<Array<{ provenance: string; metadata: Record<string, unknown> | null }>>,
    ]);
    const questionCategories: Record<string, number> = {};
    for (const question of questions) {
      const qualification = question.metadata?.qualification as { category?: string } | undefined;
      const category = qualification?.category ?? "non_qualifiée";
      questionCategories[category] = (questionCategories[category] ?? 0) + 1;
      // Les propositions ne se cachent pas derrière « observé » : la provenance
      // propre est comptée à part.
      const proposed = question.provenance === "proposed";
      if (proposed) questionCategories["proposées"] = (questionCategories["proposées"] ?? 0) + 1;
    }
    return NextResponse.json({ configured: true, datasets, geoClusters: geoClusters.length, questionCategories, projectName: projects[0]?.name ?? "", projectWebsite: projects[0]?.website ?? "" });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
