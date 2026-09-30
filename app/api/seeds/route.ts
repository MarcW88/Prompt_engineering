import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

const seedTypes = new Set(["keyword", "theme", "brand", "competitor", "product", "problem"]);

export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, seeds: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const seeds = await supabaseRest("seeds", { query: `select=*&project_id=eq.${encodeURIComponent(projectId)}&order=priority.desc,created_at.asc` });
    return NextResponse.json({ configured: true, seeds });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId || !Array.isArray(body.seeds)) return NextResponse.json({ error: "projectId et seeds sont requis." }, { status: 400 });
  const rows = body.seeds.flatMap((seed: Record<string, unknown>) => {
    const value = String(seed.value ?? "").trim();
    const seedType = String(seed.seedType ?? "keyword");
    if (!value || !seedTypes.has(seedType)) return [];
    return [{ project_id: body.projectId, value, seed_type: seedType, priority: Math.max(0, Math.min(100, Number(seed.priority ?? 50))), language: String(seed.language ?? "fr"), market: String(seed.market ?? "BE"), source: String(seed.source ?? "manual"), enabled: seed.enabled !== false }];
  });
  if (!rows.length) return NextResponse.json({ error: "Aucun seed valide." }, { status: 400 });
  try {
    const seeds = await supabaseRest("seeds", { method: "POST", query: "on_conflict=project_id,value,seed_type,language,market", prefer: "resolution=merge-duplicates,return=representation", body: rows });
    return NextResponse.json({ seeds }, { status: 201 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Import impossible." }, { status: 502 });
  }
}

export async function DELETE(request: Request) {
  const id = new URL(request.url).searchParams.get("id");
  if (!id) return NextResponse.json({ error: "id est requis." }, { status: 400 });
  try {
    await supabaseRest("seeds", { method: "DELETE", query: `id=eq.${encodeURIComponent(id)}`, prefer: "return=minimal" });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Suppression impossible." }, { status: 502 });
  }
}
