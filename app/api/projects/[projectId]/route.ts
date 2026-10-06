import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

const tables = ["analysis_costs", "datasets", "jobs", "prompts", "clusters", "questions", "signals", "sources", "seeds"];

export async function DELETE(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false }, { status: 503 });
  const { projectId } = await params;
  try {
    const active = await supabaseRest<Array<{ id: string }>>("jobs", {
      query: `select=id&project_id=eq.${encodeURIComponent(projectId)}&status=in.(pending,running)&limit=1`,
    });
    if (active.length) return NextResponse.json({ error: "Annulez les jobs actifs avant de supprimer le workspace." }, { status: 409 });
    for (const table of tables) {
      await supabaseRest(table, {
        method: "DELETE",
        query: `project_id=eq.${encodeURIComponent(projectId)}`,
        prefer: "return=minimal",
      });
    }
    await supabaseRest("projects", {
      method: "DELETE",
      query: `id=eq.${encodeURIComponent(projectId)}`,
      prefer: "return=minimal",
    });
    return NextResponse.json({ deleted: true });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Suppression impossible." }, { status: 502 });
  }
}
