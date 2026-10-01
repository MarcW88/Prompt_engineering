import { createHash, randomUUID } from "crypto";
import { NextResponse } from "next/server";
import { parseGscCsv } from "@/lib/data/gsc";
import { isSupabaseConfigured, supabaseRest } from "@/lib/data/supabase";

export async function POST(request: Request) {
  const form = await request.formData();
  const file = form.get("file");
  const projectId = String(form.get("projectId") ?? "");
  const minWords = Math.max(1, Number(form.get("minWords") ?? 10));
  const queryPattern = String(form.get("queryPattern") ?? "").trim();
  if (!(file instanceof File)) return NextResponse.json({ error: "Un fichier CSV est requis." }, { status: 400 });
  let signals;
  try {
    signals = parseGscCsv(await file.text(), minWords, queryPattern);
  } catch {
    return NextResponse.json({ error: "La regex GSC est invalide." }, { status: 400 });
  }
  if (!projectId || !isSupabaseConfigured()) return NextResponse.json({ configured: false, imported: 0, parsed: signals.length, preview: signals.slice(0, 10) });
  try {
    const sources = await supabaseRest<Array<{ id: string }>>("sources", { method: "POST", body: [{ project_id: projectId, kind: "gsc", name: file.name, config: { min_words: minWords, query_pattern: queryPattern || null } }] });
    const sourceId = sources[0]?.id;
    const rows = signals.map((signal) => ({ id: randomUUID(), project_id: projectId, source_id: sourceId, source_type: "gsc_conversation", platform: "google_search_console", raw_text: signal.raw_text, title: signal.title, url: "https://search.google.com/search-console", metadata: signal.metadata, content_hash: createHash("sha256").update(signal.raw_text.toLowerCase()).digest("hex") }));
    if (rows.length) await supabaseRest("signals", { method: "POST", query: "on_conflict=project_id,content_hash", prefer: "resolution=ignore-duplicates,return=representation", body: rows });
    return NextResponse.json({ configured: true, imported: rows.length, parsed: signals.length, sourceId });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Import impossible." }, { status: 502 });
  }
}
