import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function GET() {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, projects: [] });
  try {
    const projects = await supabaseRest("projects", { query: "select=*&order=created_at.asc" });
    return NextResponse.json({ configured: true, projects });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.name || !body?.slug) return NextResponse.json({ error: "name et slug sont requis." }, { status: 400 });
  try {
    const projects = await supabaseRest("projects", { method: "POST", body: [{ name: body.name, slug: body.slug, website: body.website ?? null, country: body.country ?? "BE", language: body.language ?? "fr" }] });
    return NextResponse.json({ projects }, { status: 201 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création impossible." }, { status: 502 });
  }
}
