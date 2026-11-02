"""Runner du dataset complet : couverture → lots → propositions → priorités.

Usage :
    python -m analysis.dataset_complete_runner <project_id> [--execute-llm] [--report chemin.json]

Sans ``--execute-llm`` : dry-run — matrice de couverture, plan de lots,
priorités sur le corpus existant, aucun appel payant.
Avec ``--execute-llm`` : génère les propositions des lots restants (coûteux,
chaque lot écrit ses lignes `questions` provenance=proposed et son coût dans
`analysis_costs` provider=openai service_category=dataset_preparation).

Les entrées sont versionnées (input_version) : un lot terminé sur la même
version n'est jamais régénéré ni refacturé.
"""
import argparse
import json
import os
import sys
from typing import Dict, List

import requests

from analysis.dataset_complete import (build_kickoff_context, completed_batch_ids,
                                       compute_coverage, input_version, make_llm_call,
                                       plan_batches, proposed_rows, run_batches)
from analysis.elmo_adapter import build_suggest_prompt, dedupe_key
from analysis.qualification import qualify_question
from analysis.dataset_complete import select_priorities
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _rest(env: Dict[str, str]):
    base = env["NEXT_PUBLIC_SUPABASE_URL"] + "/rest/v1"
    headers = {"apikey": env["SUPABASE_SECRET_KEY"], "Authorization": f"Bearer {env['SUPABASE_SECRET_KEY']}", "Content-Type": "application/json"}
    return base, headers


def _get(base, headers, table, params):
    resp = requests.get(f"{base}/{table}", params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


def load_context(base, headers, project_id):
    questions = _get(base, headers, "questions", {"project_id": f"eq.{project_id}", "select": "id,text,provenance,language,metadata", "limit": "1000"})
    jobs = _get(base, headers, "jobs", {"project_id": f"eq.{project_id}", "kind": "eq.collect_sources", "order": "created_at.desc", "limit": "1"})
    source_config = (jobs[0].get("input") or {}).get("source_config") or {} if jobs else {}
    project = _get(base, headers, "projects", {"id": f"eq.{project_id}", "select": "name,language,website", "limit": "1"})
    return questions, source_config, (project[0] if project else {})


def build_report(questions, source_config, version):
    coverage = compute_coverage(questions, source_config)
    return {
        "input_version": version,
        "questions_total": len(questions),
        "coverage": [vars(c) for c in coverage],
        "uncovered": [c.value for c in coverage if not c.covered],
        "batches": [vars(b) for b in plan_batches(coverage, source_config, version)],
    }


def main():
    parser = argparse.ArgumentParser(description="Dataset complet : couverture, lots, priorités")
    parser.add_argument("project_id")
    parser.add_argument("--execute-llm", action="store_true", help="appels payants — réservé à autorisation explicite")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    env = {k: v for line in open(".env").read().splitlines() if "=" in line for k, v in [line.split("=", 1)]}
    base, headers = _rest(env)
    questions, source_config, project = load_context(base, headers, args.project_id)
    version = input_version(source_config, questions)
    report = build_report(questions, source_config, version)

    if args.execute_llm:
        api_key = env.get("OPENAI_API_KEY", "")
        if not api_key:
            sys.exit("OPENAI_API_KEY absent — génération impossible")
        batches = plan_batches([_cell(c) for c in report["coverage"]], source_config, version)
        completed = completed_batch_ids(questions)
        todo = [b for b in batches if b.batch_id not in completed]
        llm = _llm_with_prompts(env, source_config, project, questions)
        produced = run_batches(todo, llm, [q["text"] for q in questions], completed)
        rows = proposed_rows(args.project_id, produced, source_config, project.get("language") or "fr", {b.batch_id: b for b in todo})
        if rows:
            requests.post(f"{base}/questions", json=rows, headers={**headers, "Prefer": "return=minimal"}).raise_for_status()
        cost_rows = [{"project_id": args.project_id, "provider": "openai", "service_category": "dataset_preparation",
                      "quantity": 1, "unit": "batch", "status": "usage_only", "currency": "usd",
                      "billing_reference": f"dataset_complete:{b.batch_id}", "note": b.objective}
                     for b in todo if b.status == "done"]
        if cost_rows:
            requests.post(f"{base}/analysis_costs", json=cost_rows, headers={**headers, "Prefer": "return=minimal"})
        report["executed_batches"] = [{"batch_id": b.batch_id, "status": b.status, "produced": b.produced, "error": b.error} for b in todo]
        report["proposed_inserted"] = len(rows)
        questions, source_config, project = load_context(base, headers, args.project_id)
        version = input_version(source_config, questions)
        report = {**report, **build_report(questions, source_config, version),
                  "executed_batches": report["executed_batches"], "proposed_inserted": len(rows)}

    # Sélection des priorités sur le corpus consolidé — même fonction de quotas
    # que le lancement ; le rapport est persisté pour l'export et l'audit.
    priorities = select_priorities(questions, source_config, 200)
    report["priorities"] = {k: v for k, v in priorities.items() if k not in ("priorities", "deferred")}
    report["priority_items"] = priorities["priorities"]
    report["deferred_items"] = priorities["deferred"]
    report["deferred_count"] = len(priorities["deferred"])
    requests.post(f"{base}/jobs", json={
        "project_id": args.project_id, "kind": "dataset_complete", "status": "completed",
        "input": {"input_version": version, "execute_llm": args.execute_llm},
        "output": report, "completed_at": _now()}, headers={**headers, "Prefer": "return=minimal"})

    if args.report:
        with open(args.report, "w") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"input_version": version, "questions": report["questions_total"],
                      "uncovered": len(report["uncovered"]), "batches_planned": len(report["batches"]),
                      "proposed_inserted": report.get("proposed_inserted", 0)}, ensure_ascii=False))


def _cell(raw):
    from analysis.dataset_complete import CoverageCell
    return CoverageCell(raw["dimension"], raw["value"], raw["observed"], raw["proposed"], raw["covered"])


def _llm_with_prompts(env, source_config, project, questions):
    """Chaque lot utilise le prompt Elmo (complément d'angles) avec le contexte
    kickoff — pas de reformulation des prompts existants."""
    inner = make_llm_call(env.get("OPENAI_API_KEY", ""))
    existing = [q["text"] for q in questions]
    url = source_config.get("domain") or (project.get("website") or "")
    brand = (source_config.get("brand_variants") or [project.get("name", "")])[0]
    kickoff = build_kickoff_context(source_config)
    competitors = source_config.get("competitors") or []

    def call(objective: str, count: int):
        base_prompt = build_suggest_prompt(
            analysis_url=f"https://{url}", brand_name=brand, website_excerpt="",
            existing_prompts=existing[-40:], existing_tags=[],
            competitors=competitors, count=count, language="fr", kickoff_context=kickoff)
        result = inner(f"{base_prompt}\nSpecific objective for THIS batch: {objective}", count)
        result.setdefault("prompts", result.get("suggestedPrompts", []))
        return result
    return call


if __name__ == "__main__":
    main()
