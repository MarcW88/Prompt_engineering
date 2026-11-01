import { isSupabaseConfigured, supabaseRest } from "./supabase";

export interface DashboardData {
  configured: boolean;
  projectId: string | null;
  projectName: string | null;
  metrics: { seeds: number; signals: number; questions: number; clusters: number; prompts: number; datasets: number; observations: number; validations: number; approved: number; stability: number };
  sources: Array<{ id: string; name: string; kind: string; enabled: boolean; last_synced_at: string | null }>;
  jobs: Array<{ kind: string; status: string }>;
  prompts: Array<{
    id: string; text: string; provenance: string; confidence: number; status: string; created_at: string;
    engines: string[]; fan_outs: number | null; trace_status: "provider_reported" | "independent_reexecution" | "none_reported" | "not_measured";
    stability: number | null; review_status: string | null;
  }>;
}

const empty: DashboardData = {
  configured: false,
  projectId: null,
  projectName: null,
  metrics: { seeds: 0, signals: 0, questions: 0, clusters: 0, prompts: 0, datasets: 0, observations: 0, validations: 0, approved: 0, stability: 0 },
  sources: [],
  jobs: [],
  prompts: [],
};

async function fetchLinked<T extends { id: string }>(table: string, ids: string[], column: string, select: string): Promise<T[]> {
  const rows: T[] = [];
  for (let index = 0; index < ids.length; index += 200) {
    rows.push(...await supabaseRest<T[]>(table, { query: `select=${select}&${column}=in.(${ids.slice(index, index + 200).join(",")})` }));
  }
  return rows;
}

export async function getDashboardData(projectId?: string): Promise<DashboardData> {
  if (!isSupabaseConfigured()) return empty;
  const projects = await supabaseRest<Array<{ id: string; name: string }>>("projects", { query: `select=id,name${projectId ? `&id=eq.${encodeURIComponent(projectId)}` : "&order=created_at.desc&limit=1"}` });
  const project = projects[0];
  const id = projectId ?? project?.id;
  if (!id) return { ...empty, configured: true };
  const encoded = encodeURIComponent(id);
  const [seeds, signals, questions, clusters, promptIds, prompts, sources, jobs, datasets] = await Promise.all([
    supabaseRest<Array<{ id: string }>>("seeds", { query: `select=id&project_id=eq.${encoded}&enabled=eq.true` }),
    supabaseRest<Array<{ id: string }>>("signals", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<Array<{ id: string }>>("questions", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<Array<{ id: string }>>("clusters", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<Array<{ id: string }>>("prompts", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<DashboardData["prompts"]>("prompts", { query: `select=id,text,provenance,confidence,status,created_at&project_id=eq.${encoded}&order=created_at.desc&limit=10` }),
    supabaseRest<DashboardData["sources"]>("sources", { query: `select=id,name,kind,enabled,last_synced_at&project_id=eq.${encoded}&order=created_at.asc` }),
    supabaseRest<DashboardData["jobs"]>("jobs", { query: `select=kind,status&project_id=eq.${encoded}&order=created_at.desc&limit=20` }),
    supabaseRest<Array<{ id: string }>>("datasets", { query: `select=id&project_id=eq.${encoded}` }),
  ]);
  const ids = promptIds.map((row) => row.id);
  const datasetIds = datasets.map((row) => row.id);
  const observations = await fetchLinked<{ id: string }>("observations", ids, "prompt_id", "id");
  const validations = await fetchLinked<{ id: string; prompt_id: string; stability_score: number }>("validations", ids, "prompt_id", "id,prompt_id,stability_score");
  const examples = await fetchLinked<{ id: string; manual_review_status: string; prompt_id: string }>("dataset_examples", datasetIds, "dataset_id", "id,manual_review_status,prompt_id");
  const stability = validations.length ? Math.round(validations.reduce((sum, row) => sum + Number(row.stability_score), 0) / validations.length * 100) : 0;
  const approved = examples.filter((row) => row.manual_review_status === "approved").length;

  // Real per-prompt aggregates for the recent-prompts table: engines actually
  // used, trace status (never "0" for an unmeasured metric), stability.
  const recentIds = prompts.map((row) => row.id);
  const recentObservations = await fetchLinked<{ id: string; prompt_id: string; engine: string; answer: string | null }>("observations", recentIds, "prompt_id", "id,prompt_id,engine,answer");
  const recentObservationIds = recentObservations.map((row) => row.id);
  const recentFanOuts = recentObservationIds.length
    ? await fetchLinked<{ id: string; observation_id: string; source: string }>("fan_outs", recentObservationIds, "observation_id", "id,observation_id,source")
    : [];
  const fanOutsByObservation = new Map<string, number>();
  const reexecutionObservations = new Set<string>();
  for (const row of recentFanOuts) {
    fanOutsByObservation.set(row.observation_id, (fanOutsByObservation.get(row.observation_id) ?? 0) + 1);
    if (row.source === "openai_responses_web_search") reexecutionObservations.add(row.observation_id);
  }
  const observationsByPrompt = new Map<string, typeof recentObservations>();
  for (const row of recentObservations) observationsByPrompt.set(row.prompt_id, [...(observationsByPrompt.get(row.prompt_id) ?? []), row]);
  const validationsByPrompt = new Map<string, number[]>();
  for (const row of validations.filter((row) => recentIds.includes(row.prompt_id))) {
    validationsByPrompt.set(row.prompt_id, [...(validationsByPrompt.get(row.prompt_id) ?? []), Number(row.stability_score)]);
  }
  const reviewByPrompt = new Map(examples.map((row) => [row.prompt_id, row.manual_review_status]));
  const enrichedPrompts = prompts.map((row) => {
    const promptObservations = (observationsByPrompt.get(row.id) ?? []).filter((o) => o.engine !== "openai_web_search");
    const engines = [...new Set(promptObservations.map((o) => o.engine))];
    const sameRunFanOuts = promptObservations.reduce((sum, o) => reexecutionObservations.has(o.id) ? sum : sum + (fanOutsByObservation.get(o.id) ?? 0), 0);
    const hasReexecution = promptObservations.some((o) => reexecutionObservations.has(o.id));
    const hasAnswer = promptObservations.some((o) => (o.answer ?? "").trim().length > 0);
    const trace_status: "provider_reported" | "independent_reexecution" | "none_reported" | "not_measured" =
      !promptObservations.length ? "not_measured"
      : sameRunFanOuts > 0 ? "provider_reported"
      : hasReexecution ? "independent_reexecution"
      : hasAnswer ? "none_reported" : "none_reported";
    const scores = validationsByPrompt.get(row.id) ?? [];
    return {
      ...row,
      engines,
      fan_outs: promptObservations.length ? sameRunFanOuts : null,
      trace_status,
      stability: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 100) : null,
      review_status: reviewByPrompt.get(row.id) ?? null,
    };
  });
  return { configured: true, projectId: id, projectName: project?.name ?? "Workspace GEO", metrics: { seeds: seeds.length, signals: signals.length, questions: questions.length, clusters: clusters.length, prompts: promptIds.length, datasets: examples.length, observations: observations.length, validations: validations.length, approved, stability }, sources, jobs, prompts: enrichedPrompts };
}
