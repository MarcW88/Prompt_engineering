import { NextResponse } from "next/server";
import { createAndTriggerJob } from "@/lib/data/jobs";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.projectId || !body?.datasetId) return NextResponse.json({ error: "projectId et datasetId sont requis." }, { status: 400 });
  const targetRuns = Number(body.targetRuns);
  if (![3, 5].includes(targetRuns)) return NextResponse.json({ error: "targetRuns doit valoir 3 ou 5." }, { status: 400 });
  const limit = Math.max(1, Math.min(500, Number(body.limit ?? (targetRuns === 3 ? 100 : 50))));
  try {
    const result = await createAndTriggerJob({ project_id: body.projectId, kind: "validate_dataset", status: "pending", input: { dataset_id: body.datasetId, target_runs: targetRuns, limit } });
    return NextResponse.json(result, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Création impossible." }, { status: 502 });
  }
}
