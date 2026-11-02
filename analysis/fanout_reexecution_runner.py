"""Ré-exécution auxiliaire bornée : fan-outs OpenAI web_search pour les
observations Bright Data sans trace de requêtes. Chaque résultat est une
observation séparée (engine=openai_web_search, relation=independent_reexecution)
liée au parent — jamais fusionnée dans les traces du run principal.

Usage : python -m analysis.fanout_reexecution_runner <project_id> <job_id> [--limit N]
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from analysis.dataset_complete_runner import _rest
from analysis.models import AnalysisRequest
from analysis.providers.openai_web_search import OpenAIWebSearchExtractor


def main():
    p = argparse.ArgumentParser()
    p.add_argument("project_id")
    p.add_argument("job_id")
    p.add_argument("--since", default="2026-11-02T16:40")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    env = {k: v for line in open(".env").read().splitlines() if "=" in line for k, v in [line.split("=", 1)]}
    import os
    os.environ.setdefault("OPENAI_API_KEY", env.get("OPENAI_API_KEY", ""))
    base, headers = _rest(env)

    parents = requests.get(f"{base}/observations",
        params={"select": "id,prompt_id,engine,country,language",
                "observed_at": f"gt.{args.since}", "provider": "eq.brightdata", "limit": "3000"},
        headers=headers).json()
    children = requests.get(f"{base}/observations",
        params={"select": "parent_observation_id", "relation": "eq.independent_reexecution", "limit": "3000"},
        headers=headers).json()
    done = {c["parent_observation_id"] for c in children if c.get("parent_observation_id")}
    prompts = requests.get(f"{base}/prompts",
        params={"select": "id,text", "project_id": f"eq.{args.project_id}", "limit": "2000"},
        headers=headers).json()
    text_by_id = {r["id"]: r["text"] for r in prompts}
    todo = [o for o in parents if o["id"] not in done and text_by_id.get(o["prompt_id"])]
    if args.limit:
        todo = todo[:args.limit]
    print(f"parents={len(parents)} déjà complétés={len(done)} à faire={len(todo)}")

    extractor = OpenAIWebSearchExtractor()
    results = {"ok": 0, "queries": 0, "errors": 0}

    def work(obs):
        prompt_text = text_by_id[obs["prompt_id"]]
        ext = extractor.extract(AnalysisRequest(prompt_text, engine=obs.get("engine") or "chatgpt",
                                              country=obs.get("country") or "BE",
                                              language=obs.get("language") or "fr"))
        link = {"relation": "independent_reexecution", "parent_observation_id": obs["id"],
                "response_id": ext["response_id"], "search_calls": ext["search_calls"], "usage": ext["usage"]}
        row = {"prompt_id": obs["prompt_id"], "provider": "openai", "engine": "openai_web_search",
               "model": ext["model"], "country": obs.get("country") or "BE", "language": obs.get("language") or "fr",
               "answer": ext.get("answer") or "", "web_search_triggered": True,
               "raw_response": link, "observed_at": datetime.now(timezone.utc).isoformat(),
               "parent_observation_id": obs["id"], "relation": "independent_reexecution"}
        rows = requests.post(f"{base}/observations", json=[row], headers={**headers, "Prefer": "return=representation"})
        if not rows.ok:
            row.pop("parent_observation_id"); row.pop("relation")
            rows = requests.post(f"{base}/observations", json=[row], headers={**headers, "Prefer": "return=representation"})
            rows.raise_for_status()
        child_id = rows.json()[0]["id"]
        if ext["queries"]:
            requests.post(f"{base}/fan_outs", headers={**headers, "Prefer": "return=minimal"}, json=[{
                "observation_id": child_id, "position": i + 1, "query": q,
                "normalized_query": " ".join(q.casefold().split()),
                "source": "openai_responses_web_search",
                "metadata": {"model": ext["model"], "response_id": ext["response_id"],
                             "relation": "independent_reexecution", "parent_observation_id": obs["id"]}}
                for i, q in enumerate(ext["queries"])]).raise_for_status()
        usage = ext.get("usage") or {}
        requests.post(f"{base}/analysis_costs", headers={**headers, "Prefer": "return=minimal"}, json=[{
            "project_id": args.project_id, "job_id": args.job_id, "provider": "openai",
            "category": "fan_out_reexecution", "quantity": 1, "unit": "executions",
            "cost_status": "usage_only", "currency": "usd",
            "external_reference": f"{args.job_id}:{child_id}",
            "metadata": {"model": ext["model"], "search_calls": ext["search_calls"],
                         "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}}])
        return len(ext["queries"])

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for obs, outcome in zip(todo, pool.map(lambda o: _safe(work, o), todo)):
            if isinstance(outcome, Exception):
                results["errors"] += 1
            else:
                results["ok"] += 1
                results["queries"] += outcome
    print(json.dumps(results, ensure_ascii=False))


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception as exc:
        return exc


if __name__ == "__main__":
    main()
