import { NextResponse } from "next/server";
import { getDashboardData } from "@/lib/data/dashboard";

export async function GET(request: Request) {
  const projectId = new URL(request.url).searchParams.get("projectId") ?? undefined;
  try {
    return NextResponse.json(await getDashboardData(projectId));
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Chargement impossible." }, { status: 502 });
  }
}
