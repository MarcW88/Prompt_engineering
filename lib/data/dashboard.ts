import { isSupabaseConfigured, supabaseRest } from "./supabase";

export interface DashboardData {
  configured: boolean;
  projectId: string | null;
  projectName: string | null;
  metrics: { seeds: number; signals: number; questions: number; clusters: number; prompts: number; datasets: number; observations: number; validations: number; approved: number; stability: number };
  sources: Array<{ id: string; name: string; kind: string; enabled: boolean; last_synced_at: string | null }>;
  jobs: Array<{ kind: string; status: string }>;
  prompts: Array<{ id: string; text: string; provenance: string; confidence: number; status: string; created_at: string }>;
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
  const observations = await fetchLinked<{ id: string; stability_score: number }>("observations", ids, "prompt_id", "id,stability_score");
  const validations = await fetchLinked<{ id: string; stability_score: number }>("validations", ids, "prompt_id", "id,stability_score");
  const examples = await fetchLinked<{ id: string; manual_review_status: string }>("dataset_examples", datasetIds, "dataset_id", "id,manual_review_status");
  const stability = validations.length ? Math.round(validations.reduce((sum, row) => sum + Number(row.stability_score), 0) / validations.length * 100) : 0;
  const approved = examples.filter((row) => row.manual_review_status === "approved").length;
  return { configured: true, projectId: id, projectName: project?.name ?? "Workspace GEO", metrics: { seeds: seeds.length, signals: signals.length, questions: questions.length, clusters: clusters.length, prompts: promptIds.length, datasets: examples.length, observations: observations.length, validations: validations.length, approved, stability }, sources, jobs, prompts };
}
