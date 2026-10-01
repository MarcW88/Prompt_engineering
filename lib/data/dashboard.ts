import { isSupabaseConfigured, supabaseRest } from "./supabase";

export interface DashboardData {
  configured: boolean;
  projectId: string | null;
  projectName: string | null;
  metrics: { questions: number; clusters: number; prompts: number; stability: number };
  sources: Array<{ id: string; name: string; kind: string; enabled: boolean; last_synced_at: string | null }>;
  prompts: Array<{ id: string; text: string; provenance: string; confidence: number; status: string; created_at: string }>;
}

const empty: DashboardData = {
  configured: false,
  projectId: null,
  projectName: null,
  metrics: { questions: 0, clusters: 0, prompts: 0, stability: 0 },
  sources: [],
  prompts: [],
};

export async function getDashboardData(projectId?: string): Promise<DashboardData> {
  if (!isSupabaseConfigured()) return empty;
  const projects = await supabaseRest<Array<{ id: string; name: string }>>("projects", { query: `select=id,name${projectId ? `&id=eq.${encodeURIComponent(projectId)}` : "&order=created_at.desc&limit=1"}` });
  const project = projects[0];
  const id = projectId ?? project?.id;
  if (!id) return { ...empty, configured: true };
  const encoded = encodeURIComponent(id);
  const [questions, clusters, promptIds, prompts, sources, validations] = await Promise.all([
    supabaseRest<Array<{ id: string }>>("questions", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<Array<{ id: string }>>("clusters", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<Array<{ id: string }>>("prompts", { query: `select=id&project_id=eq.${encoded}` }),
    supabaseRest<DashboardData["prompts"]>("prompts", { query: `select=id,text,provenance,confidence,status,created_at&project_id=eq.${encoded}&order=created_at.desc&limit=10` }),
    supabaseRest<DashboardData["sources"]>("sources", { query: `select=id,name,kind,enabled,last_synced_at&project_id=eq.${encoded}&order=created_at.asc` }),
    supabaseRest<Array<{ stability_score: number }>>("validations", { query: "select=stability_score&order=created_at.desc&limit=100" }),
  ]);
  const stability = validations.length ? Math.round(validations.reduce((sum, row) => sum + Number(row.stability_score), 0) / validations.length * 100) : 0;
  return { configured: true, projectId: id, projectName: project?.name ?? "Workspace GEO", metrics: { questions: questions.length, clusters: clusters.length, prompts: promptIds.length, stability }, sources, prompts };
}
