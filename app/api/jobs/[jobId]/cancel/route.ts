import { NextResponse } from "next/server";
import { cancelCloudRunExecution } from "@/lib/cloud-run";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function POST(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, error: "Supabase n'est pas configuré." }, { status: 503 });
  const { jobId } = await params;
  try {
    const jobs = await supabaseRest<Array<{ id: string; status: string; cloud_execution_id?: string | null }>>("jobs", {
      query: `select=id,status,cloud_execution_id&id=eq.${encodeURIComponent(jobId)}&limit=1`,
    });
    const job = jobs[0];
    if (!job) return NextResponse.json({ error: "Job introuvable." }, { status: 404 });
    if (!["pending", "running"].includes(job.status)) return NextResponse.json({ error: "Seuls les jobs en attente ou en cours peuvent être annulés." }, { status: 409 });
    if (job.cloud_execution_id) await cancelCloudRunExecution(job.cloud_execution_id);
    const cancelledAt = new Date().toISOString();
    const updated = await supabaseRest<Array<{ id: string; status: string }>>("jobs", {
      method: "PATCH",
      query: `id=eq.${encodeURIComponent(jobId)}&status=in.(pending,running)`,
      body: { status: "cancelled", error: "Annulé manuellement.", heartbeat_at: cancelledAt, completed_at: cancelledAt },
    });
    return NextResponse.json({ cancelled: true, job: updated[0] ?? null });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Annulation impossible." }, { status: 502 });
  }
}
