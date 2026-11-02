"""Classeur destiné aux collègues — 5 onglets, sans coûts internes.

Usage :
    python -m analysis.colleague_export <project_id> <sortie.xlsx>

Onglets : Dataset complet · Priorités de mesure · Couverture du kickoff ·
Sources et parcours · Résultats disponibles. Les statuts sont colorés :
vert=contrôle satisfait, jaune=à revoir/manque, rouge=erreur/rejet,
gris=non exécuté, bleu=priorité. Les formulations proposées ne sont jamais
présentées comme observées ; les non exécutées jamais comme testées.
"""
import json
import os
import sys
from typing import Dict, List

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

FILL = {"green": "C6EFCE", "yellow": "FFEB9C", "red": "FFC7CE", "grey": "D9D9D9", "blue": "BDD7EE"}
FILL_FONT = {"green": "006100", "yellow": "9C6500", "red": "9C0006", "grey": "595959", "blue": "1F4E79"}


def _rest(env):
    return (env["NEXT_PUBLIC_SUPABASE_URL"] + "/rest/v1",
            {"apikey": env["SUPABASE_SECRET_KEY"], "Authorization": f"Bearer {env['SUPABASE_SECRET_KEY']}"})


def _get(base, headers, table, params):
    resp = requests.get(f"{base}/{table}", params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _sheet(wb, title, headers, rows, widths=None, status_col=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(h, 18 if len(h) < 14 else 30)
    for r in ws.iter_rows(min_row=2):
        for c in r:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    if status_col and status_col in headers:
        idx = headers.index(status_col)
        for r in ws.iter_rows(min_row=2):
            status = (r[idx].value or "").strip().lower()
            color = {"satisfait": "green", "à revoir": "yellow", "manque": "yellow",
                     "erreur": "red", "rejet": "red", "exclu": "red",
                     "non exécuté": "grey", "non mesuré": "grey",
                     "priorité": "blue", "exécuté": "green"}.get(status)
            if color:
                r[idx].fill = PatternFill("solid", fgColor=FILL[color])
                r[idx].font = Font(color=FILL_FONT[color])
    return ws


def main():
    project_id, out = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "export-collegues.xlsx"
    env = {k: v for line in open(".env").read().splitlines() if "=" in line for k, v in [line.split("=", 1)]}
    base, headers = _rest(env)

    questions = _get(base, headers, "questions",
                     {"project_id": f"eq.{project_id}", "select": "id,text,provenance,language,signal_id,metadata", "limit": "2000"})
    signals = _get(base, headers, "signals",
                   {"project_id": f"eq.{project_id}", "select": "id,source_type,platform,url,title,raw_text", "limit": "2000"})
    signal_by_id = {s["id"]: s for s in signals}
    report = _get(base, headers, "jobs",
                  {"project_id": f"eq.{project_id}", "kind": "eq.dataset_complete",
                   "status": "eq.completed", "order": "created_at.desc", "limit": "1"})
    report = (report[0].get("output") or {}) if report else {}
    priority_ids = {p["question_id"] for p in report.get("priority_items", [])}
    deferred_ids = {d["question_id"]: d.get("defer_reason", "") for d in report.get("deferred_items", [])}
    prompts_rows = _get(base, headers, "prompts",
                        {"project_id": f"eq.{project_id}", "select": "id,text", "limit": "2000"})
    prompt_text = {p["id"]: p.get("text", "") for p in prompts_rows}
    examples = _get(base, headers, "dataset_examples",
                    {"select": "id,status,prompt_id", "limit": "5000"})
    observations = _get(base, headers, "observations",
                        {"select": "id,prompt_id,engine,answer,relation,observed_at", "limit": "3000"})
    obs_by_prompt = {}
    for o in observations:
        obs_by_prompt.setdefault(o.get("prompt_id"), []).append(o)
    executed_texts = {}
    for ex in examples:
        text = prompt_text.get(ex.get("prompt_id"), "")
        if not text:
            continue
        obs = obs_by_prompt.get(ex.get("prompt_id"), [])
        if obs or ex.get("status") in ("executing", "accepted", "rejected"):
            executed_texts[text] = {"status": ex.get("status"), "obs": obs}

    def prov(q):
        return (q.get("metadata") or {}).get("provenance_label") or q.get("provenance") or "observed"

    def qual(q):
        return (q.get("metadata") or {}).get("qualification") or {}

    def status(q):
        if qual(q).get("category") == "hors_périmètre":
            return "exclu"
        if q["id"] in priority_ids:
            return "priorité"
        return "à revoir" if q["id"] in deferred_ids else "satisfait"

    wb = Workbook()
    wb.remove(wb.active)

    # 1. Dataset complet
    _sheet(wb, "Dataset complet",
           ["Formulation ID", "Intention ID", "Formulation exacte", "Catégorie", "Thème kickoff",
            "Provenance", "Source", "Justification", "Priorité mesure", "Statut"],
           [[(q.get("metadata") or {}).get("formulation_id", q["id"]),
             (q.get("metadata") or {}).get("intent_id", ""),
             q.get("text", ""), qual(q).get("category", ""),
             qual(q).get("kickoff_theme", ""), prov(q),
             (signal_by_id.get(q.get("signal_id")) or {}).get("url", ""),
             qual(q).get("justification", ""),
             "oui" if q["id"] in priority_ids else ("non — " + deferred_ids.get(q["id"], "non sélectionnée") if q["id"] in deferred_ids else ""),
             status(q)] for q in questions],
           widths={"Formulation exacte": 55, "Justification": 40, "Source": 35},
           status_col="Statut")

    # 2. Priorités de mesure
    prios = report.get("priority_items", [])
    _sheet(wb, "Priorités de mesure",
           ["Rang", "Formulation ID", "Formulation exacte", "Catégorie", "Thème kickoff",
            "Provenance", "Justification sélection", "Moteur", "Passages", "Statut réel"],
           [[n + 1, p["question_id"], p["text"], p["category"], p.get("kickoff_theme", ""),
             p["provenance"], p.get("selection_reason", ""), "ChatGPT", 1,
             "exécuté" if p["text"] in executed_texts and executed_texts[p["text"]].get("obs") else "non exécuté"]
            for n, p in enumerate(prios)],
           widths={"Formulation exacte": 55, "Justification sélection": 45},
           status_col="Statut réel")

    # 3. Couverture du kickoff
    coverage = report.get("coverage", [])
    _sheet(wb, "Couverture du kickoff",
           ["Dimension", "Valeur", "Observées", "Proposées", "Statut"],
           [[c.get("dimension"), c.get("value"), c.get("observed", 0), c.get("proposed", 0),
             "satisfait" if c.get("covered") else "manque"] for c in coverage],
           status_col="Statut")

    # 4. Sources et parcours
    rows = []
    for q in questions:
        s = signal_by_id.get(q.get("signal_id")) or {}
        rows.append([s.get("platform") or s.get("source_type", ""), s.get("url", ""),
                     (s.get("raw_text") or s.get("title") or "")[:300], "",
                     q.get("text", ""), (q.get("metadata") or {}).get("intent_id", ""),
                     q["id"], prov(q)])
    _sheet(wb, "Sources et parcours",
           ["Source", "URL", "Extrait", "Auteur", "Question", "Intention", "Formulation ID", "Provenance"],
           rows, widths={"Extrait": 50, "URL": 35, "Question": 50})

    # 5. Résultats disponibles
    rows = []
    for text, info in executed_texts.items():
        obs = info.get("obs") or []
        if obs:
            for o in obs:
                rows.append([text, o.get("engine", ""), 1,
                             "exécuté" if o.get("answer") else "erreur",
                             (o.get("answer") or "")[:500], ""])
        else:
            rows.append([text, "ChatGPT", 1, "non exécuté", "", ""])
    _sheet(wb, "Résultats disponibles",
           ["Formulation exacte", "Moteur", "Passages", "Statut", "Réponse (extrait)", "Citations"],
           rows, widths={"Formulation exacte": 55, "Réponse (extrait)": 60, "Citations": 40},
           status_col="Statut")

    wb.save(out)
    print(json.dumps({"file": out, "questions": len(questions), "priorites": len(prios),
                      "executees": sum(1 for v in executed_texts.values() if v.get("obs"))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
