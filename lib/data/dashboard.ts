import { isSupabaseConfigured, supabaseRest } from "./supabase";
import { traceKind } from "./observations";

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
  const examples = await fetchLinked<{ id: string; manual_review_status: string; prompt_id: string; stability_score: number | null; completed_runs: number | null; target_runs: number | null }>("dataset_examples", datasetIds, "dataset_id", "id,manual_review_status,prompt_id,stability_score,completed_runs,target_runs");
  // Stability is only "measured" once the required repetitions actually ran;
  // below that the honest state is "not measured", not a perfect average.
  const measuredStability = examples.filter((row) => row.stability_score != null && Number(row.completed_runs ?? 0) >= Math.max(3, Number(row.target_runs ?? 0)));
  const stability = measuredStability.length ? Math.round(measuredStability.reduce((sum, row) => sum + Number(row.stability_score), 0) / measuredStability.length * 100) : 0;
  const approved = examples.filter((row) => row.manual_review_status === "approved").length;

  // Real per-prompt aggregates for the recent-prompts table: engines actually
  // used, trace status (never "0" for an unmeasured metric), stability.
  const recentIds = prompts.map((row) => row.id);
  const recentObservations = await fetchLinked<{ id: string; prompt_id: string; engine: string; provider: string; answer: string | null }>("observations", recentIds, "prompt_id", "id,prompt_id,engine,provider,answer");
  const recentObservationIds = recentObservations.map((row) => row.id);
  const recentFanOuts = recentObservationIds.length
    ? await fetchLinked<{ id: string; observation_id: string; source: string }>("fan_outs", recentObservationIds, "observation_id", "id,observation_id,source")
    : [];
  const fanOutSourcesByObservation = new Map<string, string[]>();
  for (const row of recentFanOuts) {
    fanOutSourcesByObservation.set(row.observation_id, [...(fanOutSourcesByObservation.get(row.observation_id) ?? []), String(row.source)]);
  }
  const observationsByPrompt = new Map<string, typeof recentObservations>();
  for (const row of recentObservations) observationsByPrompt.set(row.prompt_id, [...(observationsByPrompt.get(row.prompt_id) ?? []), row]);
  const reviewByPrompt = new Map(examples.map((row) => [row.prompt_id, row.manual_review_status]));
  // Stability per prompt comes from scored dataset examples and is only
  // reported when the required repetitions actually completed.
  const stabilitySumByPrompt = new Map<string, { sum: number; count: number }>();
  for (const example of measuredStability) {
    const entry = stabilitySumByPrompt.get(example.prompt_id) ?? { sum: 0, count: 0 };
    entry.sum += Number(example.stability_score);
    entry.count += 1;
    stabilitySumByPrompt.set(example.prompt_id, entry);
  }
  const enrichedPrompts = prompts.map((row) => {
    const promptObservations = observationsByPrompt.get(row.id) ?? [];
    const engines = [...new Set(promptObservations.map((o) => o.engine))];
    // Per-observation classification on its own surface: a same-run OpenAI
    // web-search trace is provider_reported for openai_web_search even though
    // the observation is an independent_reexecution relative to its parent.
    const kinds = promptObservations.map((o) => traceKind(fanOutSourcesByObservation.get(o.id) ?? [], o.provider, o.engine));
    const sameRunFanOuts = promptObservations.reduce((sum, o, index) => kinds[index] === "provider_reported" ? sum + (fanOutSourcesByObservation.get(o.id) ?? []).length : sum, 0);
    const hasReexecutionTrace = kinds.some((kind) => kind === "independent_reexecution");
    const hasAnswer = promptObservations.some((o) => (o.answer ?? "").trim().length > 0);
    const trace_status: "provider_reported" | "independent_reexecution" | "none_reported" | "not_measured" =
      !promptObservations.length ? "not_measured"
      : sameRunFanOuts > 0 ? "provider_reported"
      : hasReexecutionTrace ? "independent_reexecution"
      : hasAnswer ? "none_reported" : "none_reported";
    const stabilityEntry = stabilitySumByPrompt.get(row.id);
    return {
      ...row,
      engines,
      fan_outs: promptObservations.length ? sameRunFanOuts : null,
      trace_status,
      stability: stabilityEntry ? Math.round(stabilityEntry.sum / stabilityEntry.count * 100) : null,
      review_status: reviewByPrompt.get(row.id) ?? null,
    };
  });
  return { configured: true, projectId: id, projectName: project?.name ?? "Workspace GEO", metrics: { seeds: seeds.length, signals: signals.length, questions: questions.length, clusters: clusters.length, prompts: promptIds.length, datasets: examples.length, observations: observations.length, validations: validations.length, approved, stability }, sources, jobs, prompts: enrichedPrompts };
}
