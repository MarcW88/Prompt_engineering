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
    await supabaseRest("jobs", { method: "PATCH", query: `id=eq.${encodeURIComponent(job.id)}`, body: { error: error instanceof Error ? error.message : "Déclenchement Cloud Run impossible" }, prefer: "return=minimal" });
    throw error;
  }
}
