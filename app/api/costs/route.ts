import { NextResponse } from "next/server";
import { supabaseRest } from "@/lib/data/supabase";

export async function GET(request: Request) {
  const projectId = new URL(request.url).searchParams.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId est requis." }, { status: 400 });
  try {
    const costs = await supabaseRest<Array<Record<string, unknown>>>("analysis_costs", { query: `select=id,job_id,dataset_id,provider,category,amount,currency,quantity,unit,cost_status,external_reference,metadata,occurred_at&project_id=eq.${encodeURIComponent(projectId)}&order=occurred_at.desc&limit=500` });
    const confirmed = costs.filter((row) => ["actual", "account_delta"].includes(String(row.cost_status)) && row.amount !== null).reduce((sum, row) => sum + Number(row.amount), 0);
    const byProvider = costs.reduce<Record<string, { confirmed: number; entries: number; pending: number }>>((result, row) => {
      const provider = String(row.provider);
      result[provider] ??= { confirmed: 0, entries: 0, pending: 0 };
      result[provider].entries += 1;
      if (["actual", "account_delta"].includes(String(row.cost_status))) result[provider].confirmed += Number(row.amount ?? 0);
      else result[provider].pending += 1;
      return result;
    }, {});
    return NextResponse.json({ currency: "usd", confirmedTotal: Math.round(confirmed * 1_000_000) / 1_000_000, byProvider, costs });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
