import { NextResponse } from "next/server";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";
import { isEligibleObservation, observedFanOutSourceFilter, traceKind } from "@/lib/data/observations";

type Row = Record<string, unknown>;

// Liste les observations avec fan-outs rapportés par le provider — cibles
// éligibles pour le job reverse_engineer (isolation par project_id via prompts).
export async function GET(request: Request) {
  if (!isSupabaseConfigured()) return NextResponse.json({ configured: false, observations: [] });
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  const encoded = encodeURIComponent(projectId);
  try {
    const prompts = await supabaseRest<Row[]>("prompts", { query: `select=id,text&project_id=eq.${encoded}&limit=20000` });
    const promptById = new Map(prompts.map((row) => [String(row.id), String(row.text)]));
    if (!prompts.length) return NextResponse.json({ configured: true, observations: [] });
    const ids = [...promptById.keys()];
    const observations: Row[] = [];
    for (let index = 0; index < ids.length; index += 200) {
      observations.push(...await supabaseRest<Row[]>("observations", {
        query: `select=id,prompt_id,provider,engine,model,answer,raw_response_error:raw_response->>error,observed_at&prompt_id=in.(${ids.slice(index, index + 200).join(",")})&order=observed_at.desc`,
      }));
    }
    const observationIds = observations.map((row) => String(row.id));
    const fanouts: Row[] = [];
    for (let index = 0; index < observationIds.length; index += 200) {
      fanouts.push(...await supabaseRest<Row[]>("fan_outs", {
        query: `select=observation_id,query,source&${observedFanOutSourceFilter()}&observation_id=in.(${observationIds.slice(index, index + 200).join(",")})`,
      }));
    }
    const countByObservation = new Map<string, number>();
    const sourceByObservation = new Map<string, Set<string>>();
    for (const row of fanouts) {
      countByObservation.set(String(row.observation_id), (countByObservation.get(String(row.observation_id)) ?? 0) + 1);
      sourceByObservation.set(String(row.observation_id), (sourceByObservation.get(String(row.observation_id)) ?? new Set()).add(String(row.source)));
    }
    const rows = observations
      .filter((row) => isEligibleObservation({ ...row, raw_response: row.raw_response_error ? { error: row.raw_response_error } : null }))
      .map((row) => ({
        id: row.id,
        prompt_text: promptById.get(String(row.prompt_id)) ?? "",
        provider: row.provider,
        engine: row.engine,
        model: row.model,
        observed_at: row.observed_at,
        fan_out_count: countByObservation.get(String(row.id)) ?? 0,
        trace_kind: traceKind(sourceByObservation.get(String(row.id)) ?? [], row.provider, row.engine),
      }))
      .filter((row) => row.fan_out_count > 0);
    return NextResponse.json({ configured: true, observations: rows });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
