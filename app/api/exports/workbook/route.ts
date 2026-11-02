import { NextResponse } from "next/server";
import ExcelJS from "exceljs";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";
import { toEurAmount, USD_EUR_RATE } from "@/lib/data/budget";
import { traceKind } from "@/lib/data/observations";

// §16.2 — one downloadable workbook, twelve linked tabs. From a final prompt
// the reader can reach its questions, source extracts, executions and costs
// via stable ids and internal hyperlinks. Long texts wrap; nothing is
// silently truncated (long answers are chunked into identified rows).

type Row = Record<string, unknown>;

const EXCEL_CELL_LIMIT = 32000;
const METHOD_VERSION = "v1.0-2026-11-01";

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

// Explicit currency conversion before aggregation (§16.3): amounts keep their
// original currency in the journal; synthesis is in EUR using a declared rate.
const EUR_RATE_SOURCE = `taux fixe ENV COST_USD_EUR_RATE = ${USD_EUR_RATE} (export du ${new Date().toISOString().slice(0, 10)})`;
const toEur = toEurAmount;

function cellText(value: unknown): string {
  // Source extracts are written as literal text — never interpreted formulas.
  const text = String(value ?? "");
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

function chunk(value: string, size = EXCEL_CELL_LIMIT): string[] {
  if (value.length <= size) return [value];
  const parts: string[] = [];
  for (let index = 0; index < value.length; index += size) parts.push(value.slice(index, index + size));
  return parts;
}

interface SheetSpec {
  name: string;
  columns: { header: string; key: string; width: number }[];
  rows: Row[];
  wrapColumns?: string[];
}

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const projectId = params.get("projectId");
  const versionId = params.get("versionId") || "";
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ error: "Supabase n'est pas configuré." }, { status: 503 });

  try {
    const project = encodeURIComponent(projectId);
    const projectRows = await supabaseRest<Row[]>("projects", { query: `select=id,name,country,language,created_at,budget_total_eur&id=eq.${project}&limit=1` });
    const projectRow = projectRows[0] ?? {};

    // ---- Frozen version (§16.1.8) ------------------------------------------------
    let frozen: Row | null = null;
    if (versionId) {
      const versions = await supabaseRest<Row[]>("jobs", { query: `select=id,output&project_id=eq.${project}&kind=eq.portfolio_finalization&order=created_at.desc` });
      frozen = versions.find((row) => String((row.output as Row)?.version_id ?? "") === versionId) ?? null;
      if (!frozen) return NextResponse.json({ error: "Version finalisée introuvable." }, { status: 404 });
    } else {
      const versions = await supabaseRest<Row[]>("jobs", { query: `select=id,output&project_id=eq.${project}&kind=eq.portfolio_finalization&order=created_at.desc&limit=1` });
      frozen = versions[0] ?? null;
    }
    const frozenVersionId = String((frozen?.output as Row | undefined)?.version_id ?? "non_finalise");

    // ---- Core data --------------------------------------------------------------
    const [seeds, signals, questions, clusters, clusterQuestions, prompts, datasets, costRows, jobs] = await Promise.all([
      supabaseRest<Row[]>("seeds", { query: `select=id,value,seed_type,priority,language,market,enabled,created_at&project_id=eq.${project}` }),
      supabaseRest<Row[]>("signals", { query: `select=id,source_type,platform,title,raw_text,url,language,theme,collected_at&project_id=eq.${project}&order=collected_at.asc` }),
      supabaseRest<Row[]>("questions", { query: `select=id,signal_id,text,provenance,language,confidence,created_at&project_id=eq.${project}` }),
      supabaseRest<Row[]>("clusters", { query: `select=id,label,representative_question,question_count,is_geo_relevant&project_id=eq.${project}` }),
      supabaseRest<Row[]>("cluster_questions", { query: `select=cluster_id,question_id&order=cluster_id` }),
      supabaseRest<Row[]>("prompts", { query: `select=id,cluster_id,text,provenance,confidence,status,expected_fan_outs,metadata,created_at&project_id=eq.${project}&order=created_at.asc` }),
      supabaseRest<Row[]>("datasets", { query: `select=id,name,status,statistics,engines,max_budget_eur,created_at,completed_at&project_id=eq.${project}&order=created_at.asc` }),
      supabaseRest<Row[]>("analysis_costs", { query: `select=id,job_id,dataset_id,provider,category,amount,currency,quantity,unit,cost_status,external_reference,metadata&project_id=eq.${project}` }),
      supabaseRest<Row[]>("jobs", { query: `select=id,kind,status,input,output,error,created_at,completed_at&project_id=eq.${project}&order=created_at.asc` }),
    ]);
    const promptIds = prompts.map((row) => String(row.id));
    const datasetIds = datasets.map((row) => String(row.id));

    const datasetExamples = datasetIds.length
      ? await fetchInBatches<Row>("dataset_examples", datasetIds, "dataset_id", "id,dataset_id,prompt_id,status,persona,journey_stage,specificity_level,quality_score,stability_score,reproduction_score,validation_tier,target_runs,completed_runs,manual_review_status,review_note,edited_prompt_text")
      : [];
    const observations = promptIds.length
      ? await fetchInBatches<Row>("observations", promptIds, "prompt_id", "id,prompt_id,relation:raw_response->>relation,parent_observation_id:raw_response->>parent_observation_id,provider,engine,model,country,language,answer,raw_response_error:raw_response->>error,executed_text:raw_response->>executed_text,web_search_triggered,observed_at")
      : [];
    const observationIds = observations.map((row) => String(row.id));
    const [fanOuts, citations] = observationIds.length
      ? await Promise.all([
          fetchInBatches<Row>("fan_outs", observationIds, "observation_id", "id,observation_id,position,query,source,metadata"),
          fetchInBatches<Row>("citations", observationIds, "observation_id", "id,observation_id,position,url,title,excerpt"),
        ])
      : [[], []];

    // ---- Indexes ----------------------------------------------------------------
    const signalById = new Map(signals.map((row) => [String(row.id), row]));
    const questionById = new Map(questions.map((row) => [String(row.id), row]));
    const clusterById = new Map(clusters.map((row) => [String(row.id), row]));
    const promptById = new Map(prompts.map((row) => [String(row.id), row]));
    const observationById = new Map(observations.map((row) => [String(row.id), row]));
    const exampleByPrompt = new Map<string, Row[]>();
    for (const example of datasetExamples) {
      const key = String(example.prompt_id);
      exampleByPrompt.set(key, [...(exampleByPrompt.get(key) ?? []), example]);
    }
    const fanSourcesByObs = new Map<string, Set<string>>();
    for (const fan of fanOuts) {
      const key = String(fan.observation_id);
      fanSourcesByObs.set(key, (fanSourcesByObs.get(key) ?? new Set()).add(String(fan.source)));
    }
    const obsByPrompt = new Map<string, Row[]>();
    for (const observation of observations) {
      const key = String(observation.prompt_id);
      obsByPrompt.set(key, [...(obsByPrompt.get(key) ?? []), observation]);
    }
    const questionsByCluster = new Map<string, Row[]>();
    for (const link of clusterQuestions) {
      const question = questionById.get(String(link.question_id));
      if (!question) continue;
      const key = String(link.cluster_id);
      questionsByCluster.set(key, [...(questionsByCluster.get(key) ?? []), question]);
    }
    const normalize = (value: unknown) => String(value ?? "").toLowerCase().replace(/\s+/g, " ").trim();
    const questionTextIndex = new Map<string, Row>();
    for (const link of clusterQuestions) {
      const question = questionById.get(String(link.question_id));
      if (question?.text) questionTextIndex.set(`${link.cluster_id}:${normalize(question.text)}`, question);
    }

    // ---- Intent inventory (§16.1.1 / F4) ----------------------------------------
    const inventoryRows: Row[] = [];
    const seenIntents = new Set<string>();
    const inventorySources = datasets.filter((row) => Array.isArray((row.statistics as Row | undefined)?.intents_identified));
    for (const dataset of inventorySources) {
      const stats = dataset.statistics as Row;
      const selected = new Set(stats.intents_selected as string[] ?? []);
      for (const intent of stats.intents_identified as string[] ?? []) {
        const key = `${dataset.id}:${intent}`;
        if (seenIntents.has(key)) continue;
        seenIntents.add(key);
        const intentPrompts = prompts.filter((p) => String((p.metadata as Row | undefined)?.intent_id ?? "") === intent);
        const representative = intentPrompts.find((p) => (p.metadata as Row | undefined)?.is_representative === true) ?? intentPrompts[0];
        inventoryRows.push({
          dataset_id: dataset.id,
          intent_id: intent,
          representative_text: representative?.text ?? "",
          variants: intentPrompts.filter((p) => (p.metadata as Row | undefined)?.is_representative === false).length,
          constraints: JSON.stringify((representative?.metadata as Row | undefined)?.constraints ?? []),
          decision: selected.has(intent) ? "sélectionnée" : "différée (plafond / budget)",
          decision_reason: selected.has(intent) ? "représentant retenu dans le pool" : "écartée par les plafonds avant exécution",
          in_final_set: intentPrompts.some((p) => (exampleByPrompt.get(String(p.id)) ?? []).some((e) => e.manual_review_status === "approved")) ? "oui" : "non",
        });
      }
    }
    // Intents visible on prompts but absent from persisted inventories (legacy).
    for (const prompt of prompts) {
      const intent = String((prompt.metadata as Row | undefined)?.intent_id ?? "");
      if (!intent || inventoryRows.some((row) => String(row.intent_id) === intent)) continue;
      inventoryRows.push({ dataset_id: "", intent_id: intent, representative_text: prompt.text, variants: "", constraints: "", decision: "hors inventaire persisté", decision_reason: "inventaire non enregistré pour ce build", in_final_set: "" });
    }

    // ---- Final prompt versions (§16.1.5) ----------------------------------------
    // When a frozen version is requested, the set, texts and results come
    // exclusively from the snapshot — later edits or approvals never leak in.
    const finalRows: Row[] = [];
    const finalRowsByPromptVersion = new Map<string, number>();
    if (versionId) {
      const frozenVersions = ((frozen?.output as Row | undefined)?.versions as Row[] | undefined) ?? [];
      for (const version of frozenVersions) {
        const prompt = promptById.get(String(version.prompt_id));
        finalRows.push({
          prompt_version_id: version.prompt_version_id,
          prompt_id: version.prompt_id,
          version: "figée",
          final_text: version.text,
          intent_id: version.intent_id ?? "",
          cluster_label: String(clusterById.get(String(version.cluster_id ?? ""))?.label ?? prompt?.cluster_id ?? ""),
          constraints_persona: "",
          origin: version.origin ?? version.provenance ?? "",
          base_questions: "voir onglet 02 (données live)",
          base_question_ids: "",
          choice_reason: "figé par finalisation",
          rejected_alternatives: "",
          approval: version.approval ?? "approved",
          surfaces_tested: ((version.surfaces_tested as string[] | undefined) ?? []).join(" | ") || "aucune",
          executed_runs: version.executed_runs ?? 0,
          trace_status: "figé — voir 06_Executions",
          stability: version.stability_score ?? "non mesurée",
          executed_state: version.executed_state ?? "",
          reconstruction_target: "",
          quality_score: version.quality_score ?? "",
          reproduction_score: version.reproduction_score ?? "",
        });
      }
    } else {
      for (const prompt of prompts) {
        for (const example of exampleByPrompt.get(String(prompt.id)) ?? []) {
          if (example.manual_review_status !== "approved") continue;
          const meta = (prompt.metadata ?? {}) as Row;
          const finalText = String(example.edited_prompt_text || prompt.text || "");
          const versionObs = (obsByPrompt.get(String(prompt.id)) ?? []).filter((obs) => String(obs.executed_text || prompt.text) === finalText);
          const directQuestions = [prompt.text, String(meta.variant_of ?? "")].filter(Boolean)
            .map((value) => questionTextIndex.get(`${prompt.cluster_id}:${normalize(value)}`)).filter(Boolean) as Row[];
          const runs = versionObs.filter((obs) => String(obs.answer ?? "").trim() && !obs.raw_response_error);
          const surfaces = [...new Set(versionObs.map((obs) => `${obs.provider}/${obs.engine}`))].join(" | ");
          const stabilityShown = Number(example.completed_runs ?? 0) >= Math.max(3, Number(example.target_runs ?? 0)) ? example.stability_score : null;
          const versions = (exampleByPrompt.get(String(prompt.id)) ?? []).length;
          const rowIndex = finalRows.length + 2;
          finalRowsByPromptVersion.set(String(example.id), rowIndex);
          finalRows.push({
            prompt_version_id: example.id,
            prompt_id: prompt.id,
            version: `v${versions}`,
            final_text: finalText,
            intent_id: String(meta.intent_id ?? ""),
            cluster_label: String(clusterById.get(String(prompt.cluster_id))?.label ?? ""),
            constraints_persona: [meta.constraints, example.persona].filter(Boolean).map((v) => JSON.stringify(v)).join(" "),
            origin: String(meta.method ?? prompt.provenance ?? ""),
            base_questions: directQuestions.map((q) => q.text).join(" || "),
            base_question_ids: directQuestions.map((q) => q.id).join(", "),
            choice_reason: "approuvé en revue humaine",
            rejected_alternatives: (exampleByPrompt.get(String(prompt.id)) ?? []).filter((e) => e.id !== example.id && e.status === "rejected").map((e) => e.id).join(", "),
            approval: String(example.manual_review_status ?? ""),
            surfaces_tested: surfaces || "aucune",
            executed_runs: runs.length,
            trace_status: [...new Set(versionObs.map((obs) => traceKind(fanSourcesByObs.get(String(obs.id)) ?? [], obs.provider, obs.engine)))].join(" | ") || "non mesuré",
            stability: stabilityShown ?? "non mesurée",
            executed_state: runs.length ? "exécutée" : "approuvée non exécutée",
            reconstruction_target: String(meta.target_observation_id ?? ""),
            category: String((meta.qualification as Row | undefined)?.category ?? "non qualifiée"),
            kickoff_theme: String((meta.qualification as Row | undefined)?.kickoff_theme ?? ""),
            qualification_justification: String((meta.qualification as Row | undefined)?.justification ?? ""),
            formulation_provenance: String(prompt.provenance ?? ""),
          });
        }
      }
    }
    // §16.1.5: 01_Prompts_finaux holds only executed versions; approved but
    // never-executed propositions live in their own tab, clearly labelled.
    const propositionRows = finalRows.filter((row) => Number(row.executed_runs ?? 0) === 0);
    const executedFinalRows = finalRows.filter((row) => Number(row.executed_runs ?? 0) > 0);

    // ---- Filiation paths (§16.2 tab 02) -----------------------------------------
    // Frozen exports stay frozen everywhere: paths only cover frozen versions
    // and their final text comes from the snapshot, never from later edits.
    const frozenOutput = (frozen?.output as Row | undefined) ?? {};
    const frozenVersionById = new Map((((frozenOutput.versions as Row[] | undefined) ?? [])).map((v) => [String(v.prompt_version_id), v]));
    const frozenPromptIds = new Set((versionId ? (frozenOutput.prompt_version_ids as string[] | undefined) ?? [] : []).map(String));
    const frozenByPromptId = new Map<string, Row>();
    for (const v of (frozenOutput.versions as Row[] | undefined) ?? []) frozenByPromptId.set(String(v.prompt_id), v);
    const pathRows: Row[] = [];
    for (const prompt of prompts) {
      const meta = (prompt.metadata ?? {}) as Row;
      const relatedQuestions = new Set<Row>();
      for (const value of [prompt.text, String(meta.variant_of ?? "")].filter(Boolean)) {
        const direct = questionTextIndex.get(`${prompt.cluster_id}:${normalize(value)}`);
        if (direct) relatedQuestions.add(direct);
      }
      for (const q of questionsByCluster.get(String(prompt.cluster_id)) ?? []) {
        if (!relatedQuestions.size) relatedQuestions.add(q); // thematic path when no direct match
      }
      if (!relatedQuestions.size) relatedQuestions.add({ id: "", text: "", signal_id: "", provenance: "reconstruction sans question source" });
      for (const question of relatedQuestions) {
        const signal = signalById.get(String(question.signal_id));
        const seed = seeds.find((s) => String(s.value).toLowerCase() === String(question.text).toLowerCase());
        for (const example of exampleByPrompt.get(String(prompt.id)) ?? [{}]) {
          if (versionId && !frozenPromptIds.has(String(example.id))) continue;
          const frozenVersion = versionId ? (frozenVersionById.get(String(example.id)) ?? frozenByPromptId.get(String(prompt.id))) : undefined;
          pathRows.push({
            final_version: versionId
              ? String(frozenVersion?.prompt_version_id ?? example.id)
              : example.manual_review_status === "approved" ? String(example.id) : "",
            campaign_id: projectId,
            seed_id: seed?.id ?? "",
            seed_value: seed?.value ?? "",
            signal_id: signal?.id ?? "",
            source_excerpt: signal ? String(signal.raw_text ?? signal.title ?? "") : "chemin absent",
            source_url: signal?.url ?? "",
            platform: signal?.platform ?? "",
            question_id: question.id ?? "",
            initial_question: question.text ?? "",
            transformed_question: String(question.provenance ?? "") === "transformed" ? question.text : "",
            cluster_id: prompt.cluster_id ?? "",
            intent_id: String(meta.intent_id ?? ""),
            candidate_prompt_id: prompt.id,
            candidate_text: prompt.text,
            reconstruction: prompt.provenance === "reverse_engineered" ? `ICL depuis observation ${String(meta.target_observation_id ?? "?")}` : "",
            final_text: String(frozenVersion?.text ?? example.edited_prompt_text ?? prompt.text ?? ""),
            step_status: versionId
              ? `figé/${String(frozenVersion?.selection_status ?? "sélectionné")}`
              : `${prompt.status ?? ""}/${example.status ?? "non candidat"}`,
          });
        }
      }
    }

    // Long source excerpts are split into identified rows — never truncated.
    const expandedPathRows: Row[] = [];
    for (const row of pathRows) {
      const parts = chunk(String(row.source_excerpt ?? ""));
      parts.forEach((part, index) => expandedPathRows.push({ ...row, part: parts.length > 1 ? `${index + 1}/${parts.length}` : "", source_excerpt: index + 1 === parts.length ? part : `${part} [suite partie ${index + 2}/${parts.length}]` }));
    }
    pathRows.length = 0;
    pathRows.push(...expandedPathRows);

    // ---- 06 Executions ------------------------------------------------------------
    const executionRows: Row[] = [];
    const executionRowById = new Map<string, number>();
    for (const obs of observations) {
      const prompt = promptById.get(String(obs.prompt_id));
      const answer = String(obs.answer ?? "");
      const parts = chunk(answer);
      parts.forEach((part, index) => {
        const rowIndex = executionRows.length + 2;
        if (index === 0) executionRowById.set(String(obs.id), rowIndex);
        executionRows.push({
          observation_id: obs.id,
          part: parts.length > 1 ? `${index + 1}/${parts.length}` : "",
          executed_text: String(obs.executed_text || prompt?.text || ""),
          prompt_id: obs.prompt_id,
          provider_api: obs.provider,
          surface_engine: obs.engine,
          model: obs.model ?? "",
          market_language: `${obs.country ?? ""}/${obs.language ?? ""}`,
          observed_at: obs.observed_at,
          result_or_error: obs.raw_response_error ? `erreur: ${String(obs.raw_response_error)}` : part,
          truncated_note: parts.length > 1 && index + 1 === parts.length ? "réponse découpée — voir lignes identifiées" : "",
          parent_observation: obs.parent_observation_id ?? "",
          relation: obs.relation ?? "same_run",
          web_search_triggered: obs.web_search_triggered,
          fanout_reason: "",
          payload_ref: `observations/${obs.id} raw_response (archive Supabase)`,
        });
      });
    }

    // ---- 07 Fanouts + citations ----------------------------------------------------
    const fanRows = fanOuts.map((fan) => ({
      id: fan.id,
      type: "fan_out",
      run_observation_id: fan.observation_id,
      query_or_url: fan.query,
      title_excerpt: "",
      position: fan.position,
      source: fan.source,
      observed_or_estimated: String(fan.source ?? "").includes("estimated") ? "estimée" : "observée",
      parent_relation: String((fan.metadata as Row | undefined)?.relation ?? "same_run"),
      parent_observation_id: String((fan.metadata as Row | undefined)?.parent_observation_id ?? ""),
    }));
    const citationRows = citations.map((citation) => ({
      id: citation.id,
      type: "citation",
      run_observation_id: citation.observation_id,
      query_or_url: citation.url,
      title_excerpt: `${citation.title ?? ""} ${citation.excerpt ?? ""}`.trim(),
      position: citation.position,
      source: "engine_citation",
      observed_or_estimated: "observée",
      parent_relation: "same_run",
      parent_observation_id: "",
    }));

    // ---- 08 Reconstruction ---------------------------------------------------------
    const reconJobs = jobs.filter((row) => row.kind === "reverse_engineer");
    const reconRows: Row[] = [];
    for (const prompt of prompts.filter((p) => p.provenance === "reverse_engineered")) {
      const meta = (prompt.metadata ?? {}) as Row;
      const examples = exampleByPrompt.get(String(prompt.id)) ?? [];
      for (const example of examples.length ? examples : [{}]) {
        reconRows.push({
          candidate_prompt_id: prompt.id,
          hypothesis_text: prompt.text,
          target_observation: String(meta.target_observation_id ?? ""),
          target_surface: String(observationById.get(String(meta.target_observation_id ?? ""))?.engine ?? ""),
          example_observations: JSON.stringify(meta.example_observation_ids ?? []),
          validation_runs: example.completed_runs ?? "",
          reproduction: example.reproduction_score ?? "",
          stability: example.stability_score ?? "non mesurée (runs insuffisants)",
          decision: `${example.status ?? ""}/${example.manual_review_status ?? "pending"}`,
        });
      }
    }
    for (const job of reconJobs) {
      const baseline = ((job.output as Row | undefined)?.baseline_evaluation ?? null) as Row | null;
      if (baseline) {
        reconRows.push({ candidate_prompt_id: `job ${job.id}`, hypothesis_text: "comparaison baseline↔ICL", target_observation: "", target_surface: "", example_observations: "", validation_runs: baseline.paired_evaluable, reproduction: `ICL moyenne ${baseline.icl_mean ?? "?"}`, stability: "", decision: `baseline moyenne ${baseline.baseline_mean ?? "?"} — ${baseline.conclusion ?? "aucun gain démontré"}` });
      }
    }
    if (!reconRows.length) reconRows.push({ candidate_prompt_id: "", hypothesis_text: "module non exécuté sur cette campagne", target_observation: "", target_surface: "", example_observations: "", validation_runs: "", reproduction: "", stability: "", decision: "absent" });

    // ---- 09 / 10 Costs -------------------------------------------------------------
    // Reconciliation (§16.3): a confirmed event replaces the pending provision
    // it settles (same provider+category, linked by external_reference or the
    // same job/dataset attribution) — it is never an additional charge.
    // 1:1 pairing: each confirmed event settles at most ONE provision — the one
    // it references directly, or the oldest matching provision on the same
    // job/scope. Other consumptions of the same job stay "non rapproché".
    const confirmedEvents = costRows.filter((row) => ["actual", "account_delta"].includes(String(row.cost_status)));
    const claimedConfirmed = new Set<string>();
    const reconciledProvisionIds = new Set<string>();
    const provisions = costRows.filter((row) => ["usage_only", "pending_reconciliation"].includes(String(row.cost_status)));
    // Pass 1 — explicit links: shared billing reference or metadata.reconciles.
    for (const prov of provisions) {
      const match = confirmedEvents.find((evt) => {
        if (claimedConfirmed.has(String(evt.id))) return false;
        const evtRef = String(evt.external_reference ?? "");
        const provRef = String(prov.external_reference ?? "");
        const evtMeta = (evt.metadata ?? {}) as Row;
        return (evtRef && evtRef === provRef) || String(evtMeta.reconciles ?? "") === String(prov.id);
      });
      if (match) {
        claimedConfirmed.add(String(match.id));
        reconciledProvisionIds.add(String(prov.id));
      }
    }
    // Pass 2 — same scope (provider+category+job), still strictly 1:1.
    for (const prov of provisions.filter((row) => !reconciledProvisionIds.has(String(row.id)))) {
      const match = confirmedEvents.find((evt) =>
        !claimedConfirmed.has(String(evt.id)) &&
        String(evt.provider) === String(prov.provider) &&
        String(evt.category) === String(prov.category) &&
        String(evt.job_id ?? "") === String(prov.job_id ?? ""));
      if (match) {
        claimedConfirmed.add(String(match.id));
        reconciledProvisionIds.add(String(prov.id));
      }
    }
    const isReconciledProvision = (row: Row) => reconciledProvisionIds.has(String(row.id));
    const costDetail = costRows.map((row) => ({
      cost_event_id: row.id,
      provider: row.provider,
      service_category: row.category,
      job_id: row.job_id ?? "",
      dataset_id: row.dataset_id ?? "",
      quantity: row.quantity ?? "",
      unit: row.unit ?? "",
      status: row.cost_status,
      currency: row.currency,
      amount: row.amount ?? "inconnu",
      estimated_unit_cost: "",
      conversion_eur: toEur(row.amount, row.currency) ? Number(toEur(row.amount, row.currency)).toFixed(4) : (row.amount ? "devise non convertible" : ""),
      billing_reference: row.external_reference ?? "",
      created_at: "",
      note: [
        String(row.cost_status) === "account_delta" ? "delta de compte partagé — non attribué à un run sans preuve" : "",
        isReconciledProvision(row) ? "provision rapprochée par un coût confirmé — non recomptée" : "",
      ].filter(Boolean).join(" ; "),
    }));
    const COST_GROUPS: Record<string, string> = { actual: "confirmé", account_delta: "confirmé", usage_only: "consommé non rapproché", pending_reconciliation: "consommé non rapproché", estimated: "inconnu", reserved: "réservé futur" };
    const synthesisMap = new Map<string, Row>();
    for (const row of costRows) {
      const group = row.amount == null ? "inconnu" : isReconciledProvision(row) ? "provision rapprochée" : COST_GROUPS[String(row.cost_status)] ?? "inconnu";
      const key = `${row.provider}|${row.category}|${String(row.currency ?? "").toLowerCase()}|${group}`;
      const entry = synthesisMap.get(key) ?? { provider: row.provider, service_category: row.category, statut: group, total_original: 0, total_eur: 0, currency: row.currency, events: 0 };
      entry.total_original = Number(entry.total_original) + Number(row.amount ?? 0);
      entry.total_eur = Number(entry.total_eur) + toEur(row.amount, row.currency);
      entry.events = Number(entry.events) + 1;
      synthesisMap.set(key, entry);
    }
    const confirmed = [...synthesisMap.values()].filter((r) => r.statut === "confirmé").reduce((sum, r) => sum + Number(r.total_eur), 0);
    const pending = [...synthesisMap.values()].filter((r) => r.statut === "consommé non rapproché").reduce((sum, r) => sum + Number(r.total_eur), 0);
    const hasUnknown = [...synthesisMap.values()].some((r) => r.statut === "inconnu") || costRows.some((r) => r.amount == null);
    const pendingJobs = jobs.filter((row) => row.status === "pending" || row.status === "running");
    // Project-wide ceiling in the same currency as the aggregate (EUR).
    const plafondEur = projectRow.budget_total_eur != null ? Number(projectRow.budget_total_eur) : null;
    const disponible = hasUnknown || pendingJobs.length
      ? "non garanti — coûts inconnus ou réservations en cours"
      : plafondEur == null ? "plafond projet non défini" : (plafondEur - confirmed - pending).toFixed(4);
    const synthesisRows = [
      ...[...synthesisMap.values()].map((r) => ({ provider: r.provider, service_category: r.service_category, statut: r.statut, total: Number(r.total_original).toFixed(4), currency: r.currency, total_eur: Number(r.total_eur).toFixed(4), events: r.events, plafond: "", disponible: "" })),
      { provider: "TOTAL", service_category: "confirmé + provision non rapprochée", statut: "total engagé", total: "", currency: "eur", total_eur: (confirmed + pending).toFixed(4), events: costRows.length, plafond: plafondEur ?? "non défini", disponible },
      ...(pendingJobs.length ? [{ provider: "réservé futur", service_category: `${pendingJobs.length} job(s) en cours`, statut: "réservé", total: "inconnu", currency: "eur", total_eur: "inconnu", events: pendingJobs.length, plafond: "", disponible: "non garanti tant que des coûts restent inconnus" }] : []),
    ];

    // ---- 00 Synthese ---------------------------------------------------------------
    const datasetsStats = datasets.map((d) => (d.statistics as Row | undefined)).filter(Boolean) as Row[];
    const intentsIdentified = Math.max(0, ...datasetsStats.map((s) => Array.isArray(s.intents_identified) ? s.intents_identified.length : 0));
    const approvedCount = finalRows.length;
    const syntheseRows = [
      { champ: "Client / campagne", valeur: `${projectRow.name ?? projectId} (${projectId})` },
      { champ: "Marché / langue", valeur: `${projectRow.country ?? ""} / ${projectRow.language ?? ""}` },
      { champ: "Date d'export", valeur: new Date().toISOString() },
      { champ: "Version méthode", valeur: METHOD_VERSION },
      { champ: "SHA code", valeur: process.env.VERCEL_GIT_COMMIT_SHA || "local-dev" },
      { champ: "Version finalisée", valeur: frozenVersionId },
      { champ: "Sources activées", valeur: [...new Set(signals.map((s) => s.source_type))].join(", ") },
      { champ: "Familles contributrices", valeur: [...new Set(signals.map((s) => s.platform))].filter(Boolean).join(", ") },
      { champ: "Seeds", valeur: seeds.length },
      { champ: "Extraits collectés", valeur: signals.length },
      { champ: "Questions", valeur: questions.length },
      { champ: "Intentions identifiées (avant plafonds)", valeur: intentsIdentified || "inventaire non persisté" },
      { champ: "Intentions couvertes", valeur: inventoryRows.filter((r) => r.decision === "sélectionnée").length },
      { champ: "Prompts finaux exécutés (01)", valeur: executedFinalRows.length },
      { champ: "Propositions approuvées non exécutées (01b)", valeur: propositionRows.length },
      { champ: "Prompts finaux approuvés (total)", valeur: approvedCount },
      { champ: "Exécutions", valeur: observations.length },
      { champ: "Limites", valeur: "traces non exposées par certains providers ; stabilité non mesurée sous 2 runs ; Perplexity exclu" },
      { champ: "Résumé financier", valeur: `engagé ${(confirmed + pending).toFixed(4)} eur (confirmé ${confirmed.toFixed(4)} + provision ${pending.toFixed(4)}) · conversion: ${EUR_RATE_SOURCE}` },
    ];

    // ---- 03 Sources_questions -------------------------------------------------------
    // Complete extracts: no silent truncation. Texts beyond the Excel cell
    // limit are split into identified rows (part x/n) with an explicit
    // pointer to the next part.
    const sourceRows: Row[] = [];
    for (const s of seeds) {
      sourceRows.push({ kind: "seed", id: s.id, part: "", text: s.value, url: "", platform: "", collected_at: s.created_at, provenance: "seed", question_id: "", direct_or_context: "", filters: `type=${s.seed_type} enabled=${s.enabled}` });
    }
    for (const s of signals) {
      const parts = chunk(String(s.raw_text ?? s.title ?? ""));
      const qids = questions.filter((q) => String(q.signal_id) === String(s.id)).map((q) => q.id).join(", ");
      parts.forEach((part, index) => {
        sourceRows.push({
          kind: "extrait", id: s.id,
          part: parts.length > 1 ? `${index + 1}/${parts.length}` : "",
          text: index + 1 === parts.length ? part : `${part} [suite partie ${index + 2}/${parts.length}]`,
          url: s.url, platform: s.platform,
          collected_at: s.collected_at, provenance: s.source_type,
          question_id: qids,
          direct_or_context: "",
          filters: s.theme ?? "",
        });
      });
    }
    for (const q of questions) {
      sourceRows.push({ kind: "question", id: q.id, part: "", text: q.text, url: signalById.get(String(q.signal_id))?.url ?? "", platform: signalById.get(String(q.signal_id))?.platform ?? "", collected_at: q.created_at, provenance: q.provenance, question_id: q.id, direct_or_context: "", filters: `confidence=${q.confidence ?? ""}` });
    }

    // ---- 05 Candidats_versions -------------------------------------------------------
    const candidateRows: Row[] = [];
    for (const prompt of prompts) {
      const meta = (prompt.metadata ?? {}) as Row;
      const examples = exampleByPrompt.get(String(prompt.id)) ?? [];
      if (!examples.length) {
        if (versionId) continue;
        candidateRows.push({ prompt_id: prompt.id, example_id: "", version_text: prompt.text, parent_version: "", reference_formulation: String(meta.variant_of ?? ""), generation_method: String(meta.method ?? prompt.provenance ?? ""), params: "", quality: "", stability: "", reproduction: "", decision: prompt.status, review_history: "", category: String((meta.qualification as Row | undefined)?.category ?? "non qualifiée"), kickoff_theme: String((meta.qualification as Row | undefined)?.kickoff_theme ?? ""), qualification_justification: String((meta.qualification as Row | undefined)?.justification ?? ""), formulation_provenance: String(prompt.provenance ?? "") });
      }
      for (const example of examples) {
        if (versionId && !frozenPromptIds.has(String(example.id))) continue;
        const frozenVersion = versionId ? frozenVersionById.get(String(example.id)) : undefined;
        candidateRows.push({
          prompt_id: prompt.id, example_id: example.id,
          version_text: String(frozenVersion?.text ?? example.edited_prompt_text ?? prompt.text ?? ""),
          parent_version: example.edited_prompt_text ? "texte original (édité)" : "",
          reference_formulation: String(meta.variant_of ?? ""),
          generation_method: String(meta.method ?? prompt.provenance ?? ""),
          params: [example.persona, example.journey_stage, example.specificity_level].filter(Boolean).join(" "),
          quality: frozenVersion?.quality_score ?? example.quality_score ?? "", stability: frozenVersion?.stability ?? example.stability_score ?? "", reproduction: frozenVersion?.reproduction_score ?? example.reproduction_score ?? "",
          decision: versionId ? `figé / approuvé` : `${example.status ?? ""} / ${example.manual_review_status ?? "pending"}`,
          review_history: example.review_note ?? "",
          category: String((meta.qualification as Row | undefined)?.category ?? "non qualifiée"),
          kickoff_theme: String((meta.qualification as Row | undefined)?.kickoff_theme ?? ""),
          qualification_justification: String((meta.qualification as Row | undefined)?.justification ?? ""),
          formulation_provenance: String(prompt.provenance ?? ""),
        });
      }
    }

    // ---- 11 Méthodes & limites ---------------------------------------------------------
    const methodRows = [
      { rubrique: "Seuil similarité dédup", valeur: "0,65", limite: "" },
      { rubrique: "Ordonnancement candidats", valeur: "représentants d'intentions avant variantes, sous tous les plafonds", limite: "" },
      { rubrique: "Stabilité", valeur: "mesurée seulement si ≥2 runs indépendants", limite: "un seul run → « non mesurée »" },
      { rubrique: "Reproduction", valeur: "score sémantique vs recherches cibles, seuil 0,65", limite: "pas de preuve de popularité" },
      { rubrique: "Surfaces", valeur: "brightdata/chatgpt, openai/openai_web_search", limite: "Perplexity exclu (dataset provider cassé)" },
      { rubrique: "Traces", valeur: "same_run vs independent_reexecution ; aucune trace synthétique", limite: "Bright Data n'expose pas les requêtes ChatGPT → réexécution OpenAI liée" },
      { rubrique: "Références externes", valeur: "query-fanout-viewer @268446b (inspecteur manuel)", limite: "pas d'intégration automatisée" },
      { rubrique: "Coûts", valeur: "confirmé / provision / réservé / inconnu", limite: "abonnements partagés non imputés" },
      { rubrique: "Budget", valeur: "RPC create_reserved_job (migration 202611010001)", limite: "non appliquée — réservation non vérifiée en prod" },
      { rubrique: "Export", valeur: METHOD_VERSION, limite: "textes >32 000 caractères découpés en lignes identifiées" },
    ];

    // ---- Assemble sheets ---------------------------------------------------------------
    const sheets: SheetSpec[] = [
      { name: "00_Synthese", columns: [{ header: "champ", key: "champ", width: 34 }, { header: "valeur", key: "valeur", width: 90 }], rows: syntheseRows, wrapColumns: ["valeur"] },
      { name: "01_Prompts_finaux", columns: ["prompt_version_id", "prompt_id", "version", "final_text", "intent_id", "cluster_label", "constraints_persona", "origin", "base_questions", "base_question_ids", "choice_reason", "rejected_alternatives", "approval", "surfaces_tested", "executed_runs", "trace_status", "stability", "executed_state", "reconstruction_target"].map((key) => ({ header: key, key, width: key.includes("text") || key.includes("questions") ? 60 : 22 })).concat(["category", "kickoff_theme", "qualification_justification", "formulation_provenance"].map((key) => ({ header: key, key, width: 26 }))), rows: executedFinalRows, wrapColumns: ["final_text", "base_questions"] },
      { name: "01b_Propositions", columns: ["prompt_version_id", "prompt_id", "final_text", "intent_id", "cluster_label", "origin", "approval", "executed_state", "category", "kickoff_theme", "formulation_provenance", "note"].map((key) => ({ header: key, key, width: key === "final_text" ? 60 : 24 })), rows: propositionRows.map((row) => ({ ...row, note: "approuvée mais jamais exécutée — non présentée comme testée" })), wrapColumns: ["final_text", "note"] },
      { name: "02_Parcours_complet", columns: ["final_version", "campaign_id", "seed_id", "seed_value", "signal_id", "part", "source_excerpt", "source_url", "platform", "question_id", "initial_question", "transformed_question", "cluster_id", "intent_id", "candidate_prompt_id", "candidate_text", "reconstruction", "final_text", "step_status"].map((key) => ({ header: key, key, width: ["source_excerpt", "initial_question", "candidate_text", "final_text", "source_url"].includes(key) ? 50 : 20 })), rows: pathRows, wrapColumns: ["source_excerpt", "initial_question", "candidate_text", "final_text"] },
      { name: "03_Sources_questions", columns: ["kind", "id", "part", "text", "url", "platform", "collected_at", "provenance", "question_id", "direct_or_context", "filters"].map((key) => ({ header: key, key, width: key === "text" || key === "url" ? 55 : 16 })), rows: sourceRows, wrapColumns: ["text"] },
      { name: "04_Intentions_decisions", columns: ["dataset_id", "intent_id", "representative_text", "variants", "constraints", "decision", "decision_reason", "in_final_set"].map((key) => ({ header: key, key, width: key === "representative_text" ? 55 : 24 })), rows: inventoryRows, wrapColumns: ["representative_text", "decision_reason"] },
      { name: "05_Candidats_versions", columns: ["prompt_id", "example_id", "version_text", "parent_version", "reference_formulation", "generation_method", "params", "quality", "stability", "reproduction", "decision", "review_history", "category", "kickoff_theme", "qualification_justification", "formulation_provenance"].map((key) => ({ header: key, key, width: ["version_text", "review_history"].includes(key) ? 55 : 24 })), rows: candidateRows, wrapColumns: ["version_text"] },
      { name: "06_Executions", columns: ["observation_id", "part", "executed_text", "prompt_id", "provider_api", "surface_engine", "model", "market_language", "observed_at", "result_or_error", "truncated_note", "parent_observation", "relation", "web_search_triggered", "fanout_reason", "payload_ref"].map((key) => ({ header: key, key, width: ["executed_text", "result_or_error", "payload_ref"].includes(key) ? 60 : 20 })), rows: executionRows, wrapColumns: ["executed_text", "result_or_error"] },
      { name: "07_Fanouts_citations", columns: ["id", "type", "run_observation_id", "query_or_url", "title_excerpt", "position", "source", "observed_or_estimated", "parent_relation", "parent_observation_id"].map((key) => ({ header: key, key, width: ["query_or_url", "title_excerpt"].includes(key) ? 55 : 22 })), rows: [...fanRows, ...citationRows], wrapColumns: ["query_or_url", "title_excerpt"] },
      { name: "08_Reconstruction", columns: ["candidate_prompt_id", "hypothesis_text", "target_observation", "target_surface", "example_observations", "validation_runs", "reproduction", "stability", "decision"].map((key) => ({ header: key, key, width: ["hypothesis_text", "example_observations", "decision"].includes(key) ? 50 : 24 })), rows: reconRows, wrapColumns: ["hypothesis_text"] },
      { name: "09_Couts_detail", columns: ["cost_event_id", "provider", "service_category", "job_id", "dataset_id", "quantity", "unit", "status", "currency", "amount", "estimated_unit_cost", "conversion_eur", "billing_reference", "created_at", "note"].map((key) => ({ header: key, key, width: key === "note" || key === "billing_reference" ? 45 : 20 })), rows: costDetail, wrapColumns: ["note"] },
      { name: "10_Couts_synthese", columns: ["provider", "service_category", "statut", "total", "currency", "total_eur", "events", "plafond", "disponible"].map((key) => ({ header: key, key, width: 26 })), rows: synthesisRows },
      { name: "11_Methodes_limites", columns: [{ header: "rubrique", key: "rubrique", width: 30 }, { header: "valeur", key: "valeur", width: 60 }, { header: "limite", key: "limite", width: 60 }], rows: methodRows, wrapColumns: ["valeur", "limite"] },
    ];

    const workbook = new ExcelJS.Workbook();
    workbook.creator = "PromptLab";
    workbook.created = new Date();
    const sheetRowById = new Map<string, Map<string, number>>(); // sheet -> id -> row
    for (const spec of sheets) {
      const ws = workbook.addWorksheet(spec.name);
      ws.columns = spec.columns;
      ws.views = [{ state: "frozen", ySplit: 1 }];
      ws.getRow(1).font = { bold: true };
      ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: spec.columns.length } };
      for (const [columnIndex, column] of spec.columns.entries()) {
        if (spec.wrapColumns?.includes(column.key)) ws.getColumn(columnIndex + 1).alignment = { wrapText: true, vertical: "top" };
      }
      const idIndex = new Map<string, number>();
      for (const row of spec.rows) {
        const excelRow = ws.addRow(spec.columns.map((column) => cellText(row[column.key] ?? "")));
        const rowId = String(row.prompt_version_id ?? row.observation_id ?? row.question_id ?? row.cost_event_id ?? row.prompt_id ?? row.id ?? "");
        if (rowId) idIndex.set(rowId, excelRow.number);
      }
      sheetRowById.set(spec.name, idIndex);
    }
    // Internal hyperlinks: final prompts → executions, paths → prompts.
    const execSheet = workbook.getWorksheet("06_Executions");
    const finalSheet = workbook.getWorksheet("01_Prompts_finaux");
    const execRows = executionRows;
    for (const [rowNumber, exec] of execRows.map((e, i) => [i + 2, e] as const)) {
      const promptId = String(exec.prompt_id);
      const targetRow = executedFinalRows.findIndex((r) => String(r.prompt_id) === promptId);
      if (targetRow >= 0) {
        const cell = execSheet!.getCell(`D${rowNumber}`);
        cell.value = { text: promptId, hyperlink: `#'01_Prompts_finaux'!A${targetRow + 2}` };
        cell.font = { color: { argb: "FF0563C1" }, underline: true };
      }
    }
    finalSheet!.eachRow((row, rowNumber) => {
      if (rowNumber === 1) return;
      const promptId = String(row.getCell(2).value ?? "");
      const firstExecRow = execRows.findIndex((e) => String(e.prompt_id) === promptId);
      if (firstExecRow >= 0) {
        const cell = row.getCell(15); // executed_runs
        cell.value = { text: String(row.getCell(15).value ?? "0"), hyperlink: `#'06_Executions'!A${firstExecRow + 2}` };
        cell.font = { color: { argb: "FF0563C1" }, underline: true };
      }
    });

    const buffer = await workbook.xlsx.writeBuffer();
    const filename = `rapport-complet-${projectRow.name ?? projectId}-${frozenVersionId}.xlsx`.replace(/[^\w.\-]+/g, "_");
    return new NextResponse(new Uint8Array(buffer as ArrayBuffer), {
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Classeur impossible." }, { status: 502 });
  }
}
