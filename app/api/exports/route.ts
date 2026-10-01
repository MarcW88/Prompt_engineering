import { NextResponse } from "next/server";
import writeExcelFile from "write-excel-file/node";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

type Row = Record<string, unknown>;

const stages = new Set(["seeds", "signals", "questions", "clusters", "dataset", "observations", "fanouts", "citations", "validations", "prompts"]);

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

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const projectId = params.get("projectId");
  const stage = params.get("stage") ?? "";
  const requestedFormat = params.get("format") ?? "csv";
  const format = ["csv", "json", "xlsx"].includes(requestedFormat) ? requestedFormat : "csv";
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  if (!stages.has(stage)) return NextResponse.json({ error: "stage invalide." }, { status: 400 });
  if (!isSupabaseConfigured()) return NextResponse.json({ error: "Supabase n'est pas configuré." }, { status: 503 });

  const project = encodeURIComponent(projectId);
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

    const prompts = await supabaseRest<Row[]>("prompts", { query: `select=id,text,provenance&project_id=eq.${project}&limit=20000` });
    const promptIds = prompts.map((row) => String(row.id));
    const promptById = new Map(prompts.map((row) => [String(row.id), row]));

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

    const observations = await fetchInBatches<Row>("observations", promptIds, "prompt_id", "id,prompt_id,provider,engine,model,country,language,answer,web_search_triggered,observed_at");
    observations.sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at)));
    const observationIds = observations.map((row) => String(row.id));
    const observationById = new Map(observations.map((row) => [String(row.id), row]));

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
