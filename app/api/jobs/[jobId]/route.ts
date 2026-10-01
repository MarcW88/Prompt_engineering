import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function DELETE(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false }, { status: 503 });
  const { jobId } = await params;
  try {
    const jobs = await supabaseRest<Array<{ id: string; status: string }>>("jobs", {
      query: `select=id,status&id=eq.${encodeURIComponent(jobId)}&limit=1`,
    });
    const job = jobs[0];
    if (!job) return NextResponse.json({ error: "Job introuvable." }, { status: 404 });
    if (["pending", "running"].includes(job.status)) return NextResponse.json({ error: "Annulez le job avant de le retirer." }, { status: 409 });
    await supabaseRest("jobs", {
      method: "PATCH",
      query: `id=eq.${encodeURIComponent(jobId)}`,
      body: { hidden_at: new Date().toISOString() },
      prefer: "return=minimal",
    });
    return NextResponse.json({ removed: true });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Suppression impossible." }, { status: 502 });
  }
}
