import { triggerCloudRunJob } from "@/lib/cloud-run";
import { supabaseRest } from "@/lib/data/supabase";

export interface JobInput {
  project_id: string;
  kind: string;
  status: "pending";
  input: Record<string, unknown>;
  max_attempts?: number;
}

export async function createAndTriggerJob(input: JobInput) {
  const jobs = await supabaseRest<Array<{ id: string }>>("jobs", { method: "POST", body: [input] });
  const job = jobs[0];
  if (!job) throw new Error("Le job Supabase n'a pas été créé.");
  try {
    const cloudRun = await triggerCloudRunJob(job.id);
    return { jobs, cloudRun };
  } catch (error) {
    await supabaseRest("jobs", { method: "PATCH", query: `id=eq.${encodeURIComponent(job.id)}`, body: { status: "failed", error: error instanceof Error ? error.message : "Déclenchement Cloud Run impossible", completed_at: new Date().toISOString() }, prefer: "return=minimal" });
    throw error;
  }
}

// Vérification du budget + création + réservation dans UNE transaction SQL
// (RPC create_reserved_job, verrou sur la ligne projet). Lève une erreur
// "budget_exceeded" si le solde disponible ne couvre pas la réserve.
export async function createReservedAndTriggerJob(input: JobInput & { reserved_cost_eur: number }) {
  const job = await supabaseRest<{ id: string }>("rpc/create_reserved_job", {
    method: "POST",
    body: {
      p_project_id: input.project_id,
      p_kind: input.kind,
      p_input: input.input,
      p_reserved_eur: input.reserved_cost_eur,
    },
  });
  if (!job?.id) throw new Error("Le job Supabase n'a pas été créé.");
  try {
    const cloudRun = await triggerCloudRunJob(job.id);
    return { jobs: [job], cloudRun };
  } catch (error) {
    await supabaseRest("jobs", { method: "PATCH", query: `id=eq.${encodeURIComponent(job.id)}`, body: { status: "failed", error: error instanceof Error ? error.message : "Déclenchement Cloud Run impossible", completed_at: new Date().toISOString() }, prefer: "return=minimal" });
    throw error;
  }
}
