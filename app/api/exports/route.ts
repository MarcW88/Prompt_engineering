import { NextResponse } from "next/server";
import writeExcelFile from "write-excel-file/node";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";
import { isEligibleObservation, observedFanOutSourceFilter, traceKind } from "@/lib/data/observations";

type Row = Record<string, unknown>;

const stages = new Set(["seeds", "signals", "questions", "clusters", "dataset", "observations", "fanouts", "citations", "validations", "prompts", "approved", "corpus", "portfolio"]);

function csvCell(value: unknown) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function toCsv(rows: Row[], columns: string[]) {
  return [columns.join(","), ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(","))].join("\n");
}

async function download(rows: Row[], columns: string[], stage: string, format: string) {
  if (format === "json") {
    return NextResponse.json({ stage, count: rows.length, rows });
  }
  if (format === "xlsx") {
    const data = [columns, ...rows.map((row) => columns.map((column) => {
      const value = row[column];
      if (value === null || value === undefined) return "";
      if (typeof value === "object") return JSON.stringify(value);
      return value as string | number | boolean | Date;
    }))];
    const buffer = await writeExcelFile(data).toBuffer();
    return new NextResponse(new Uint8Array(buffer), {
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="${stage}.xlsx"`,
      },
    });
  }
  return new NextResponse(toCsv(rows, columns), {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${stage}.csv"`,
    },
  });
}

function inList(ids: string[]) {
  return `in.(${ids.join(",")})`;
}

async function fetchInBatches<RowType extends Row>(table: string, ids: string[], column: string, select: string, batchSize = 200): Promise<RowType[]> {
  const rows: RowType[] = [];
  for (let index = 0; index < ids.length; index += batchSize) {
    const batch = ids.slice(index, index + batchSize);
    rows.push(...await supabaseRest<RowType[]>(table, { query: `select=${select}&${column}=${inList(batch)}` }));
  }
  return rows;
}

async function countRows(table: string, query: string) {
  const rows = await supabaseRest<Array<{ id: string }>>(table, { query: `select=id&${query}&limit=50000` });
  return rows.length;
}

async function countLinkedRows(table: string, ids: string[], column: string) {
  const rows = await fetchInBatches<{ id: string }>(table, ids, column, "id");
  return rows.length;
}

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const projectId = params.get("projectId");
  const stage = params.get("stage") ?? "";
  const requestedFormat = params.get("format") ?? "csv";
  const format = ["csv", "json", "xlsx"].includes(requestedFormat) ? requestedFormat : "csv";
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ error: "Supabase n'est pas configuré." }, { status: 503 });

  const project = encodeURIComponent(projectId);
  if (stage === "summary") {
    try {
      const promptIds = (await supabaseRest<Array<{ id: string }>>("prompts", { query: `select=id&project_id=eq.${project}&limit=50000` })).map((row) => row.id);
      const datasetIds = (await supabaseRest<Array<{ id: string }>>("datasets", { query: `select=id&project_id=eq.${project}&limit=50000` })).map((row) => row.id);
      const observationIds = (await fetchInBatches<{ id: string }>("observations", promptIds, "prompt_id", "id")).map((row) => row.id);
      const counts = {
        seeds: await countRows("seeds", `project_id=eq.${project}`),
        signals: await countRows("signals", `project_id=eq.${project}`),
        questions: await countRows("questions", `project_id=eq.${project}`),
        clusters: await countRows("clusters", `project_id=eq.${project}`),
        dataset: await countLinkedRows("dataset_examples", datasetIds, "dataset_id"),
        prompts: promptIds.length,
        observations: observationIds.length,
        fanouts: await countLinkedRows("fan_outs", observationIds, "observation_id"),
        citations: await countLinkedRows("citations", observationIds, "observation_id"),
        validations: await countLinkedRows("validations", promptIds, "prompt_id"),
        portfolio: promptIds.length,
        corpus: (await fetchInBatches<{ id: string }>("fan_outs", observationIds, "observation_id", `id&${observedFanOutSourceFilter()}`)).length,
      };
      return NextResponse.json({ counts });
    } catch (error) {
      return NextResponse.json({ error: error instanceof Error ? error.message : "Résumé impossible." }, { status: 502 });
    }
  }
  if (!stages.has(stage)) return NextResponse.json({ error: "stage invalide." }, { status: 400 });

  try {
    if (stage === "seeds") {
      const rows = await supabaseRest<Row[]>("seeds", { query: `select=id,value,seed_type,priority,language,market,enabled,created_at&project_id=eq.${project}&order=priority.desc` });
      return download(rows, ["id", "value", "seed_type", "priority", "language", "market", "enabled", "created_at"], stage, format);
    }
    if (stage === "signals") {
      const rows = await supabaseRest<Row[]>("signals", { query: `select=id,source_type,platform,title,raw_text,url,language,theme,brand,collected_at&project_id=eq.${project}&order=collected_at.desc` });
      return download(rows, ["id", "source_type", "platform", "title", "raw_text", "url", "language", "theme", "brand", "collected_at"], stage, format);
    }
    if (stage === "questions") {
      const rows = await supabaseRest<Row[]>("questions", { query: `select=id,signal_id,text,provenance,language,confidence,created_at&project_id=eq.${project}&order=created_at.desc` });
      return download(rows, ["id", "signal_id", "text", "provenance", "language", "confidence", "created_at"], stage, format);
    }
    if (stage === "clusters") {
      const rows = await supabaseRest<Row[]>("clusters", { query: `select=id,label,representative_question,question_count,source_count,is_geo_relevant,created_at&project_id=eq.${project}&order=question_count.desc` });
      return download(rows, ["id", "label", "representative_question", "question_count", "source_count", "is_geo_relevant", "created_at"], stage, format);
    }
    if (stage === "prompts") {
      const rows = await supabaseRest<Row[]>("prompts", { query: `select=id,cluster_id,text,provenance,confidence,status,expected_fan_outs,created_at&project_id=eq.${project}&order=created_at.desc` });
      return download(rows.map((row) => ({ ...row, expected_fan_outs: JSON.stringify(row.expected_fan_outs ?? []) })), ["id", "cluster_id", "text", "provenance", "confidence", "status", "expected_fan_outs", "created_at"], stage, format);
    }
    if (stage === "approved") {
      const datasets = await supabaseRest<Row[]>("datasets", { query: `select=id&project_id=eq.${project}&order=created_at.desc` });
      const datasetIds = datasets.map((row) => String(row.id));
      const examples = await fetchInBatches<Row>("dataset_examples", datasetIds, "dataset_id", "id,prompt_id,status,manual_review_status,edited_prompt_text,persona,journey_stage,specificity_level,pre_execution_score,quality_score,stability_score,reproduction_score,validation_tier,target_runs,completed_runs,created_at");
      const approvedExamples = examples.filter((row) => row.status === "accepted" && row.manual_review_status === "approved");
      const promptIds = approvedExamples.map((row) => String(row.prompt_id));
      const prompts = await fetchInBatches<{ id: string; text: string; provenance: string; confidence: number }>("prompts", promptIds, "id", "id,text,provenance,confidence");
      const promptById = new Map(prompts.map((row) => [String(row.id), row]));
      const rows = approvedExamples.map((example) => ({
        ...example,
        prompt_text: example.edited_prompt_text || promptById.get(String(example.prompt_id))?.text || "",
        provenance: promptById.get(String(example.prompt_id))?.provenance || "",
        confidence: promptById.get(String(example.prompt_id))?.confidence || 0,
      }));
      return download(rows, ["id", "prompt_text", "provenance", "confidence", "persona", "journey_stage", "specificity_level", "pre_execution_score", "quality_score", "stability_score", "reproduction_score", "validation_tier", "target_runs", "completed_runs", "created_at"], stage, format);
    }

    const prompts = await supabaseRest<Row[]>("prompts", { query: `select=id,text,provenance&project_id=eq.${project}&limit=20000` });
    const promptIds = prompts.map((row) => String(row.id));
    const promptById = new Map(prompts.map((row) => [String(row.id), row]));

    if (stage === "portfolio") {
      // §10 business portfolio: one dossier per prompt, grouped by intent,
      // explaining every selection and exclusion. An edited text is a new,
      // unexecuted version — its scores stay with the original formulation.
      const fullPrompts = await supabaseRest<Row[]>("prompts", { query: `select=id,cluster_id,text,provenance,confidence,status,expected_fan_outs,metadata,created_at&project_id=eq.${project}&limit=20000&order=created_at.asc` });
      const clusterIds = [...new Set(fullPrompts.map((row) => String(row.cluster_id)).filter((id) => id && id !== "null"))];
      const clusterById = new Map((clusterIds.length ? await supabaseRest<Row[]>("clusters", { query: `select=id,label&project_id=eq.${project}` }) : []).map((row) => [String(row.id), String(row.label ?? "")]));
      const datasets = await supabaseRest<Row[]>("datasets", { query: `select=id&project_id=eq.${project}` });
      const examples = await fetchInBatches<Row>("dataset_examples", datasets.map((row) => String(row.id)), "dataset_id", "prompt_id,status,manual_review_status,review_note,edited_prompt_text,quality_score,stability_score,reproduction_score,completed_runs,target_runs,validation_tier");
      const exampleByPrompt = new Map<string, Row>();
      for (const example of examples) {
        const key = String(example.prompt_id);
        const current = exampleByPrompt.get(key);
        if (!current || String(example.status) === "accepted") exampleByPrompt.set(key, example);
      }
      const obsCounts = new Map<string, number>();
      for (const row of await fetchInBatches<Row>("observations", promptIds, "prompt_id", "prompt_id,answer,raw_response->>error")) {
        const key = String(row.prompt_id);
        if ((row.answer ?? "").toString().trim() && !row.error) obsCounts.set(key, (obsCounts.get(key) ?? 0) + 1);
      }
      const rows = fullPrompts.map((prompt) => {
        const meta = (prompt.metadata ?? {}) as Record<string, unknown>;
        const example = exampleByPrompt.get(String(prompt.id));
        const edited = example?.edited_prompt_text ? String(example.edited_prompt_text) : "";
        return {
          id: prompt.id,
          intent_id: String(meta.intent_id ?? meta.cluster_id ?? ""),
          cluster_label: clusterById.get(String(prompt.cluster_id)) ?? "",
          role: meta.is_representative === false ? "variant" : meta.is_representative === true ? "representative" : "candidate",
          variant_of: String(meta.variant_of ?? ""),
          text: prompt.text,
          edited_text: edited || null,
          text_state: edited ? "unexecuted_version" : String(prompt.status ?? ""),
          provenance: prompt.provenance,
          origin: String(meta.method ?? prompt.provenance ?? ""),
          reconstruction_target_observation: String(meta.target_observation_id ?? ""),
          cluster_id: prompt.cluster_id,
          executed_runs: obsCounts.get(String(prompt.id)) ?? 0,
          quality_score: example?.quality_score ?? null,
          stability_score: example && Number(example.completed_runs ?? 0) >= Math.max(3, Number(example.target_runs ?? 0)) ? example.stability_score : null,
          reproduction_score: example?.reproduction_score ?? null,
          selection_status: example?.status ?? "not_selected",
          review_status: example?.manual_review_status ?? "pending",
          review_note: example?.review_note ?? null,
          confidence: prompt.confidence,
          created_at: prompt.created_at,
        };
      });
      return download(rows, ["id", "intent_id", "cluster_label", "role", "variant_of", "text", "edited_text", "text_state", "provenance", "origin", "reconstruction_target_observation", "executed_runs", "quality_score", "stability_score", "reproduction_score", "selection_status", "review_status", "review_note", "confidence", "created_at"], stage, format);
    }

    if (stage === "dataset") {
      const datasets = await supabaseRest<Row[]>("datasets", { query: `select=id,name,status,created_at&project_id=eq.${project}&order=created_at.desc` });
      const datasetIds = datasets.map((row) => String(row.id));
      const datasetById = new Map(datasets.map((row) => [String(row.id), row]));
      const examples = await fetchInBatches<Row>("dataset_examples", datasetIds, "dataset_id", "id,dataset_id,prompt_id,status,persona,journey_stage,specificity_level,pre_execution_score,quality_score,stability_score,reproduction_score,validation_tier,target_runs,completed_runs,manual_review_status,reviewed_at,review_note,edited_prompt_text,selected_for_execution,created_at");
      examples.sort((a, b) => Number(b.quality_score ?? 0) - Number(a.quality_score ?? 0));
      const rows = examples.map((example) => ({
        ...example,
        dataset_name: datasetById.get(String(example.dataset_id))?.name,
        prompt_text: promptById.get(String(example.prompt_id))?.text,
        prompt_provenance: promptById.get(String(example.prompt_id))?.provenance,
      }));
      return download(rows, ["id", "dataset_name", "status", "prompt_text", "prompt_provenance", "persona", "journey_stage", "specificity_level", "pre_execution_score", "quality_score", "stability_score", "reproduction_score", "validation_tier", "target_runs", "completed_runs", "manual_review_status", "reviewed_at", "review_note", "selected_for_execution", "created_at"], stage, format);
    }

    const observationRows = await fetchInBatches<Row>("observations", promptIds, "prompt_id", "id,prompt_id,provider,engine,model,country,language,answer,raw_response_error:raw_response->>error,web_search_triggered,observed_at");
    const observations: Row[] = observationRows.map((row) => ({ ...row, raw_response: row.raw_response_error ? { error: row.raw_response_error } : null }));
    observations.sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at)));
    const observationIds = observations.map((row) => String(row.id));
    const observationById = new Map(observations.map((row) => [String(row.id), row]));

    if (stage === "corpus") {
      // Corpus d'apprentissage reconstruction (contrat §7) : uniquement des
      // observations avec fan-outs réellement rapportés par le provider,
      // le prompt exact exécuté, et aucune requête synthétique.
      const fanRows = await fetchInBatches<Row>("fan_outs", observationIds, "observation_id", `observation_id,query,source&${observedFanOutSourceFilter()}&order=position.asc`);
      const fanByObservation = new Map<string, string[]>();
      const sourceByObservation = new Map<string, Set<string>>();
      for (const row of fanRows) {
        const key = String(row.observation_id);
        fanByObservation.set(key, [...(fanByObservation.get(key) ?? []), String(row.query)]);
        sourceByObservation.set(key, (sourceByObservation.get(key) ?? new Set()).add(String(row.source)));
      }
      const datasets = await supabaseRest<Row[]>("datasets", { query: `select=id&project_id=eq.${project}` });
      const examples = await fetchInBatches<Row>("dataset_examples", datasets.map((row) => String(row.id)), "dataset_id", "prompt_id,status");
      const acceptedPrompts = new Set(examples.filter((row) => row.status === "accepted").map((row) => String(row.prompt_id)));
      // Corpus éligible : prompts acceptés, trace valide (réponse non vide,
      // pas d'erreur provider), provider cohérent. Les observations rejetées ou
      // en erreur restent visibles dans l'export brut "observations".
      const strictOnly = new URL(request.url).searchParams.get("strict") === "1";
      const rows = observations
        .filter((observation) => (fanByObservation.get(String(observation.id)) ?? []).length > 0)
        .filter(isEligibleObservation)
        .filter((observation) => acceptedPrompts.has(String(observation.prompt_id)))
        .filter((observation) => !strictOnly || traceKind(sourceByObservation.get(String(observation.id)) ?? [], observation.provider, observation.engine) === "provider_reported")
        .map((observation) => ({
          project_id: projectId,
          prompt_id: observation.prompt_id,
          prompt: promptById.get(String(observation.prompt_id))?.text ?? "",
          observation_id: observation.id,
          provider: observation.provider,
          engine: observation.engine,
          model: observation.model ?? null,
          country: observation.country,
          language: observation.language,
          observed_at: observation.observed_at,
          fan_outs: JSON.stringify(fanByObservation.get(String(observation.id)) ?? []),
          trace_kind: traceKind(sourceByObservation.get(String(observation.id)) ?? [], observation.provider, observation.engine),
          status: "accepted",
          raw_response_reference: `observations:${observation.id}`,
        }));
      if (format === "json") {
        return NextResponse.json({ stage, count: rows.length, rows: rows.map((row) => ({ ...row, fan_outs: JSON.parse(String(row.fan_outs)) })) });
      }
      return download(rows, ["project_id", "prompt_id", "prompt", "observation_id", "provider", "engine", "model", "country", "language", "observed_at", "fan_outs", "trace_kind", "status", "raw_response_reference"], stage, format);
    }

    if (stage === "observations") {
      const rows = observations.map((row) => ({ ...row, prompt_text: promptById.get(String(row.prompt_id))?.text, prompt_provenance: promptById.get(String(row.prompt_id))?.provenance }));
      return download(rows, ["id", "prompt_text", "prompt_provenance", "provider", "engine", "model", "country", "language", "answer", "web_search_triggered", "observed_at"], stage, format);
    }
    if (stage === "fanouts") {
      const rows = await fetchInBatches<Row>("fan_outs", observationIds, "observation_id", "id,observation_id,position,query,normalized_query");
      rows.sort((a, b) => Number(a.position) - Number(b.position));
      return download(rows.map((row) => ({ ...row, prompt_text: promptById.get(String(observationById.get(String(row.observation_id))?.prompt_id))?.text })), ["id", "observation_id", "position", "prompt_text", "query", "normalized_query"], stage, format);
    }
    if (stage === "citations") {
      const rows = await fetchInBatches<Row>("citations", observationIds, "observation_id", "id,observation_id,position,url,title,excerpt");
      rows.sort((a, b) => Number(a.position) - Number(b.position));
      return download(rows.map((row) => ({ ...row, prompt_text: promptById.get(String(observationById.get(String(row.observation_id))?.prompt_id))?.text })), ["id", "observation_id", "position", "prompt_text", "url", "title", "excerpt"], stage, format);
    }

    const validations = await fetchInBatches<Row>("validations", promptIds, "prompt_id", "id,prompt_id,observation_id,fan_out_reproduction_score,citation_overlap_score,stability_score,overall_score,created_at");
    validations.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    const rows = validations.map((row) => ({ ...row, prompt_text: promptById.get(String(row.prompt_id))?.text }));
    return download(rows, ["id", "prompt_text", "observation_id", "fan_out_reproduction_score", "citation_overlap_score", "stability_score", "overall_score", "created_at"], stage, format);
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Export impossible." }, { status: 502 });
  }
}
