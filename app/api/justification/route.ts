import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";
import { traceKind } from "@/lib/data/observations";

// §5 mandatory justification table: reconciled counts across
// collection → needs → selection → execution → result, plus the generated
// client summary. Counts never mix units: technical source, platform and
// deduplicated extracts are reported separately.
export async function GET(request: Request) {
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ error: "Supabase non configuré." }, { status: 503 });
  const encoded = encodeURIComponent(projectId);
  try {
    const [signals, questions, clusters, prompts, datasets] = await Promise.all([
      supabaseRest<Array<{ id: string; platform: string; source_type: string }>>("signals", { query: `select=id,platform,source_type&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ id: string; provenance: string; signal_id: string | null }>>("questions", { query: `select=id,provenance,signal_id&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ id: string; is_geo_relevant: boolean }>>("clusters", { query: `select=id,is_geo_relevant&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ id: string; provenance: string; status: string; metadata: Record<string, unknown> }>>("prompts", { query: `select=id,provenance,status,metadata&project_id=eq.${encoded}` }),
      supabaseRest<Array<{ id: string }>>("datasets", { query: `select=id&project_id=eq.${encoded}` }),
    ]);
    const datasetIds = datasets.map((row) => row.id);
    const examples = datasetIds.length
      ? await supabaseRest<Array<{ id: string; prompt_id: string; status: string; manual_review_status: string | null; completed_runs: number | null; target_runs: number | null; reproduction_score: number | null }>>("dataset_examples", { query: `select=id,prompt_id,status,manual_review_status,completed_runs,target_runs,reproduction_score&dataset_id=in.(${datasetIds.join(",")})` })
      : [];
    const promptIds = prompts.map((row) => row.id);
    const observations = promptIds.length
      ? await supabaseRest<Array<{ id: string; prompt_id: string; engine: string; provider: string; answer: string | null; error: string | null }>>("observations", { query: `select=id,prompt_id,engine,provider,answer,raw_response->>error&prompt_id=in.(${promptIds.join(",")})` })
      : [];
    const observationIds = observations.map((row) => row.id);
    const fanOuts = observationIds.length
      ? await supabaseRest<Array<{ observation_id: string; source: string }>>("fan_outs", { query: `select=observation_id,source&observation_id=in.(${observationIds.join(",")})` })
      : [];
    const fanByObservation = new Map<string, string[]>();
    for (const row of fanOuts) fanByObservation.set(row.observation_id, [...(fanByObservation.get(row.observation_id) ?? []), String(row.source)]);

    const count = <T,>(rows: T[], predicate: (row: T) => boolean) => rows.filter(predicate).length;
    const uniq = <T,>(rows: T[], key: (row: T) => string | null | undefined) => new Set(rows.map(key).filter(Boolean)).size;

    const collection = {
      raw_extracts: signals.length,
      deduplicated_extracts: signals.length, // content_hash uniqueness is enforced at insert.
      platforms: uniq(signals, (row) => row.platform),
      source_families: uniq(signals, (row) => row.source_type),
    };
    const needs = {
      questions_observed: count(questions, (row) => row.provenance === "observed"),
      questions_transformed: count(questions, (row) => row.provenance === "transformed"),
      questions_synthetic: count(questions, (row) => row.provenance === "synthetic"),
      clusters: clusters.length,
      geo_relevant_clusters: count(clusters, (row) => row.is_geo_relevant),
      intents_identified: uniq(prompts, (row) => String(row.metadata?.intent_id ?? "")),
    };
    const selection = {
      prompts_total: prompts.length,
      representatives: count(prompts, (row) => row.metadata?.is_representative === true),
      variants: count(prompts, (row) => row.metadata?.is_representative === false && !!row.metadata?.variant_of),
      synthetic: count(prompts, (row) => row.provenance === "synthetic"),
      reconstructed: count(prompts, (row) => row.provenance === "reverse_engineered"),
      retained: count(examples, (row) => row.status === "accepted"),
      rejected: count(examples, (row) => row.status === "rejected"),
      approved: count(examples, (row) => row.manual_review_status === "approved"),
      coverage: needs.intents_identified
        ? Math.round(uniq(examples.filter((row) => row.status === "accepted").map((row) => String(prompts.find((prompt) => prompt.id === row.prompt_id)?.metadata?.intent_id ?? "")).filter(Boolean), (value) => value) / needs.intents_identified * 100)
        : null,
    };
    const executionsBySurface = new Map<string, { runs: number; succeeded: number; failed: number; with_traces: number }>();
    for (const observation of observations) {
      const entry = executionsBySurface.get(observation.engine) ?? { runs: 0, succeeded: 0, failed: 0, with_traces: 0 };
      entry.runs += 1;
      const failed = !!observation.error || !(observation.answer ?? "").trim();
      if (failed) entry.failed += 1; else entry.succeeded += 1;
      if (traceKind(fanByObservation.get(observation.id) ?? [], observation.provider, observation.engine) === "provider_reported") entry.with_traces += 1;
      executionsBySurface.set(observation.engine, entry);
    }
    const execution = {
      runs_total: observations.length,
      by_surface: Object.fromEntries(executionsBySurface),
      fan_outs_stored: fanOuts.length,
    };
    const reconstructedExamples = examples.filter((row) => prompts.find((prompt) => prompt.id === row.prompt_id)?.provenance === "reverse_engineered");
    const result = {
      portfolio_approved: selection.approved,
      reconstructions_evaluated: reconstructedExamples.length,
      reconstructions_validated: count(reconstructedExamples, (row) => row.reproduction_score != null && Number(row.completed_runs ?? 0) >= Math.max(3, Number(row.target_runs ?? 0))),
      measurement_limits: [
        "Les plafonds sont des contraintes d'exécution, pas une preuve de représentativité.",
        "La couverture porte sur les intentions identifiées dans ce corpus, pas sur tous les utilisateurs.",
      ],
    };
    const summary = `${selection.retained} prompts retenus couvrent ${selection.coverage ?? "?"}% des ${needs.intents_identified} intentions admissibles identifiées dans ce corpus, à partir de ${collection.deduplicated_extracts} extraits dédupliqués issus de ${collection.source_families} familles de sources. Les variantes sont regroupées ; les intentions non couvertes restent différées.`;
    return NextResponse.json({ collection, needs, selection, execution, result, summary });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Justification impossible." }, { status: 502 });
  }
}
