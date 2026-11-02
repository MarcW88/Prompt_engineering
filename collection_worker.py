#!/usr/bin/env python3
import argparse
import hashlib
import math
import os
import re
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from analysis.baseline_eval import HeldOutTarget, evaluate_held_out, nearest_baseline
from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder
from analysis.dataset_quality import score_dataset_example
from analysis.dataset_funnel import estimate_cost, intent_first_order, score_candidates, stratified_sample
from analysis.models import AnalysisObservation, AnalysisRequest, PromptCandidate, PromptProvenance
from analysis.providers import BrightDataProvider, DataForSEOProvider, OpenAILLMProvider, OpenAIWebSearchExtractor, OxylabsProvider
from analysis.question_pipeline import OpenAIProcessor, cluster_questions, signals_to_questions
from analysis.qualification import qualify_question, select_with_quotas
from analysis.signatures import build_signature, signature_similarity
from analysis.icl_reconstruction import ICLPromptReconstructor
from analysis.reconstruction import ReconstructionExample
from models.seed import Seed, SeedType, deduplicate_seeds
from scrapers import ForumScraper, ReviewScraper, SerpScraper, SocialScraper
from utils.config_loader import load_config, neutral_config

# Fan-out sources admitted into the learning corpus: provider-reported queries
# only (Bright Data response metadata, or OpenAI web-search fallback when
# Bright Data does not expose the queries). Mirrors OBSERVED_FAN_OUT_SOURCES
# in lib/data/observations.ts.
OBSERVED_FAN_OUT_SOURCES = ("brightdata", "openai_responses_web_search")


def EXAMPLE_SCORE_COLUMNS(scores):
    """dataset_examples only has numeric score columns; trace_status and other
    diagnostics stay in prompt/job metadata, not in the table."""
    allowed = ("coverage_score", "stability_score", "reproduction_score",
        "semantic_reproduction_score", "redundancy_score", "quality_score")
    return {key: scores.get(key) for key in allowed if key in scores}

# ICL examples and reconstruction targets must come from traces observed in the
# SAME run on the SAME surface. An independent re-execution measures another
# surface and can never stand in for the target engine's fan-outs. An
# openai_web_search observation's own queries ARE same-run for that surface.
def same_run_fan_out_source(provider: str, engine: str) -> str:
    if engine == "openai_web_search" or provider == "openai":
        return "openai_responses_web_search"
    return provider or "brightdata"

ELIGIBLE_PROVIDERS = ("brightdata", "openai")


load_dotenv()


def semantic_scorer():
    """Retourne un scorer sémantique (embeddings OpenAI, cache) ou None si la
    clé est absente. signature: (expected_queries, observed_queries) -> float,
    moyenne du meilleur appariement cosinus attendu → observé."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    cache = {}

    def embed(texts):
        missing = [text for text in texts if text not in cache]
        if missing:
            response = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"), "input": missing},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()["data"]
            if len(data) != len(missing):
                raise ValueError("Incomplete embeddings response")
            for row in data:
                cache[missing[row["index"]]] = row["embedding"]
        return [cache[text] for text in texts]

    def cosine(a, b):
        if len(a) != len(b) or not a or not any(a) or not any(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))

    def scorer(expected, observed):
        expected_vectors = embed(expected)
        observed_vectors = embed(observed)
        if not expected_vectors or not observed_vectors:
            return 0.0
        return sum(max(cosine(vector, other) for other in observed_vectors) for vector in expected_vectors) / len(expected_vectors)

    return scorer


def clamp_collection_budget(value) -> int:
    try:
        return max(1, min(200, int(value)))
    except (TypeError, ValueError):
        return 10


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "client"


def detect_language(text: str) -> str:
    try:
        from langdetect import detect
        return detect(text[:2000])
    except Exception:
        return ""


class SupabaseRest:
    def __init__(self):
        self.url = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
        self.secret = os.getenv("SUPABASE_SECRET_KEY", "")
        if not self.url or not self.secret:
            raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SECRET_KEY are required")
        self.headers = {"apikey": self.secret, "Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}

    def request(self, method: str, table: str, query: str = "", body=None, prefer: str = "return=representation"):
        headers = {**self.headers, "Prefer": prefer}
        url = f"{self.url}/rest/v1/{table}{'?' + query if query else ''}"
        response = requests.request(method, url, headers=headers, json=body, timeout=60)
        if not response.ok:
            raise RuntimeError(f"Supabase {response.status_code}: {response.text[:500]} (url: {url[:500]})")
        return response.json() if response.text else None

    def rpc(self, function: str, body: Dict):
        response = requests.post(f"{self.url}/rest/v1/rpc/{function}", headers=self.headers, json=body, timeout=60)
        response.raise_for_status()
        return response.json() if response.text else None


class JobHeartbeat:
    def __init__(self, db: SupabaseRest, job_id: str, worker_id: str, interval: int = 30):
        self.db = db
        self.job_id = job_id
        self.worker_id = worker_id
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.db.request("PATCH", "jobs", f"id=eq.{self.job_id}&worker_id=eq.{self.worker_id}&status=eq.running", {"heartbeat_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
            except Exception:
                pass


class CollectionWorker:
    def __init__(self, config_path: str, worker_id: str = "", cloud_execution_id: str = ""):
        self.db = SupabaseRest()
        self.config_path = config_path
        raw_worker_id = worker_id or os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        # Supabase PostgREST can reject colons in equality filters; keep the id URL-safe.
        self.worker_id = re.sub(r"[^a-zA-Z0-9_-]", "-", raw_worker_id)[:64]
        self.cloud_execution_id = cloud_execution_id or os.getenv("CLOUD_RUN_EXECUTION") or os.getenv("CLOUD_RUN_TASK_ID") or "local"
        self.fanout_extractor = OpenAIWebSearchExtractor() if os.getenv("OPENAI_API_KEY") else None
        # Auxiliary fan-out extraction: an OpenAI web-search re-execution is
        # fired per observation whose provider reported no searches. Désactiver
        # via OPENAI_FANOUT_FALLBACK=0 ou build_config.fanout_fallback=false.
        self.fanout_fallback_enabled = os.getenv("OPENAI_FANOUT_FALLBACK", "1") != "0"

    def _execute_analysis(self, provider, request: AnalysisRequest):
        observation = provider.execute(request)
        observation.metadata["response_source"] = observation.provider
        observation.metadata["fan_out_source"] = observation.provider
        return observation

    def _execute_analysis_batch(self, provider, requests: list[AnalysisRequest]) -> list:
        if hasattr(provider, "execute_many"):
            observations = provider.execute_many(requests)
            for observation in observations:
                observation.metadata["response_source"] = observation.provider
                observation.metadata["fan_out_source"] = observation.provider
            return observations
        return [self._execute_analysis(provider, request) for request in requests]

    def _persist_reexecution(self, prompt: Dict, parent_observation_id: str, parent: AnalysisObservation, job: Optional[Dict] = None):
        """Persist the OpenAI web-search fallback as its own observation, linked
        to the run it complements. It never merges into the parent's traces."""
        if not self.fanout_extractor:
            return None
        request = AnalysisRequest(parent.prompt, engine=parent.engine, country=parent.country, language=parent.language)
        try:
            extracted = self.fanout_extractor.extract(request)
        except Exception:
            return None
        link = {"relation": "independent_reexecution", "parent_observation_id": parent_observation_id,
                "response_id": extracted["response_id"], "search_calls": extracted["search_calls"], "usage": extracted["usage"]}
        row = {"prompt_id": prompt["id"], "provider": "openai", "engine": "openai_web_search",
            "model": extracted["model"], "country": parent.country, "language": parent.language,
            "answer": extracted.get("answer") or "", "web_search_triggered": True,
            "raw_response": link, "observed_at": datetime.now(timezone.utc).isoformat()}
        try:
            rows = self.db.request("POST", "observations", body=[{**row, "parent_observation_id": parent_observation_id, "relation": "independent_reexecution"}])
        except Exception:
            rows = self.db.request("POST", "observations", body=[row])
        reexecution_id = rows[0]["id"]
        if extracted["queries"]:
            self.db.request("POST", "fan_outs", body=[{
                "observation_id": reexecution_id, "position": index + 1, "query": query,
                "normalized_query": " ".join(query.casefold().split()), "source": "openai_responses_web_search",
                "metadata": {"model": extracted["model"], "response_id": extracted["response_id"],
                             "relation": "independent_reexecution", "parent_observation_id": parent_observation_id}}
                for index, query in enumerate(extracted["queries"])])
        if job:
            usage = extracted.get("usage") or {}
            self._record_cost(job, "openai", "fan_out_reexecution", quantity=1, unit="executions",
                cost_status="usage_only", external_reference=f"{job['id']}:{reexecution_id}",
                metadata={"model": extracted["model"], "search_calls": extracted["search_calls"],
                          "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")})
        return reexecution_id

    def _record_cost(self, job: Dict, provider: str, category: str, amount=None, quantity=None, unit=None, cost_status="actual", external_reference=None, metadata=None, dataset_id=None, estimated_unit_cost=None):
        reference = external_reference or f"{job['id']}:{provider}:{category}"
        # Les coûts non rapprochés portent une estimation pour que l'engagement
        # reste couvert par la provision résiduelle du job (reservation_open).
        if amount is None and quantity and estimated_unit_cost:
            amount = round(float(quantity) * float(estimated_unit_cost), 6)
        rows = self.db.request("POST", "analysis_costs", "on_conflict=provider,category,external_reference", [{
            "project_id": job["project_id"], "job_id": job["id"], "dataset_id": dataset_id,
            "provider": provider, "category": category, "amount": amount, "currency": "usd",
            "quantity": quantity, "unit": unit, "cost_status": cost_status,
            "external_reference": reference, "metadata": metadata or {},
        }], "resolution=merge-duplicates,return=representation")
        return rows[0] if rows else None

    def _brightdata_account_cost(self):
        api_key = os.getenv("BRIGHTDATA_API_KEY", "")
        dataset_id = os.getenv("BRIGHTDATA_CHATGPT_DATASET_ID", "")
        if not api_key or not dataset_id:
            return None
        today = datetime.now(timezone.utc).date()
        response = requests.post("https://api.brightdata.com/costs/export/json", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"dimension": "web_apis", "filters": {}, "from": today.isoformat(), "to": (today + timedelta(days=1)).isoformat()}, timeout=30)
        response.raise_for_status()
        data = response.json()
        return float((data.get("total") or {}).get(dataset_id, 0))

    def _persist_observation(self, prompt: Dict, observation, job: Optional[Dict] = None, parent_observation_id: Optional[str] = None):
        raw_response = observation.raw_response
        if observation.metadata.get("executed_text"):
            raw_response = {**raw_response, "executed_text": observation.metadata["executed_text"]}
        row = {"prompt_id": prompt["id"], "provider": observation.provider, "engine": observation.engine, "model": observation.model, "country": observation.country, "language": observation.language, "answer": observation.answer, "web_search_triggered": observation.web_search_triggered, "raw_response": raw_response, "observed_at": observation.observed_at.isoformat()}
        fan_relation = "same_run"
        if parent_observation_id:
            row["parent_observation_id"] = parent_observation_id
            row["relation"] = "independent_reexecution"
            row["raw_response"] = {**raw_response, "relation": "independent_reexecution", "parent_observation_id": parent_observation_id}
            fan_relation = "independent_reexecution"
        try:
            observation_rows = self.db.request("POST", "observations", body=[row])
        except Exception:
            observation_rows = self.db.request("POST", "observations", body=[{k: v for k, v in row.items() if k not in ("parent_observation_id", "relation")}])
        observation_id = observation_rows[0]["id"]
        if observation.fan_outs:
            self.db.request("POST", "fan_outs", body=[{"observation_id": observation_id, "position": index + 1, "query": query, "normalized_query": " ".join(query.casefold().split()), "source": observation.metadata.get("fan_out_source", observation.provider), "metadata": {"model": observation.metadata.get("fan_out_model"), "response_id": observation.metadata.get("fan_out_response_id"), "relation": fan_relation, "parent_observation_id": parent_observation_id}} for index, query in enumerate(observation.fan_outs)])
        if observation.citations:
            self.db.request("POST", "citations", body=[{"observation_id": observation_id, "position": citation.position or index + 1, "url": citation.url, "title": citation.title, "excerpt": citation.text} for index, citation in enumerate(observation.citations)])
        # Fallback OpenAI : nouvelle exécution indépendante — observation séparée,
        # jamais fusionnée dans les traces du run parent.
        if getattr(self, "fanout_fallback_enabled", os.getenv("OPENAI_FANOUT_FALLBACK", "1") != "0") and not observation.fan_outs and observation.answer and not parent_observation_id:
            reexecution_id = self._persist_reexecution(prompt, observation_id, observation, job=job)
            if reexecution_id:
                observation.metadata["reexecution_observation_id"] = reexecution_id
        return observation_id

    def _run_once(self, provider, candidate, example, engine, run_index, project, phase):
        observation = self._execute_analysis(provider, AnalysisRequest(
            prompt=candidate.text, engine=engine, country=project.get("country", "BE"),
            language=project.get("language", "fr"),
            metadata={"example_id": example["id"], "run_index": run_index, "phase": phase},
        ))
        # Version link: the exact text executed is stored with the run so an
        # edited formulation never inherits the previous version's results.
        observation.metadata["executed_text"] = candidate.text
        return observation

    def _stored_observations(self, prompt_id: str, engines=None):
        engine_filter = f"&engine=in.({','.join(engines)})" if engines else ""
        rows = self.db.request("GET", "observations", f"select=*&prompt_id=eq.{prompt_id}{engine_filter}&order=observed_at.asc")
        rows = [row for row in rows if row.get("answer") and not (row.get("raw_response") or {}).get("error")]
        observation_ids = [row["id"] for row in rows]
        fan_out_rows = self.db.request("GET", "fan_outs", f"select=observation_id,query&observation_id=in.({','.join(observation_ids)})") if observation_ids else []
        fan_outs = {}
        for row in fan_out_rows:
            fan_outs.setdefault(row["observation_id"], []).append(row["query"])
        return [AnalysisObservation(
            prompt="", provider=row["provider"], engine=row["engine"], answer=row.get("answer", ""),
            fan_outs=fan_outs.get(row["id"], []), citations=[], country=row.get("country", "BE"),
            language=row.get("language", "fr"), model=row.get("model", ""),
            web_search_triggered=row.get("web_search_triggered"), raw_response=row.get("raw_response", {}),
        ) for row in rows]

    def _job_cost_summary(self, job_id: str):
        rows = self.db.request("GET", "analysis_costs", f"select=amount,cost_status&job_id=eq.{job_id}")
        actual = sum(float(row.get("amount") or 0) for row in rows if row.get("cost_status") in {"actual", "account_delta"})
        pending = any(row.get("cost_status") in {"usage_only", "pending_reconciliation", "unavailable"} for row in rows)
        return round(actual, 6), "partial" if pending else "reconciled"

    def _settle_reservation(self, job: Dict) -> Dict:
        """Provision résiduelle après fin de job : les coûts non rapprochés
        (montants estimés) restent engagés tant qu'aucune dépense réelle ne les
        a remplacés via l'upsert sur (provider, category, external_reference).
        reservation_open=false libère la réservation une fois tout rapproché."""
        rows = self.db.request("GET", "analysis_costs", f"select=amount,cost_status&job_id=eq.{job['id']}")
        residual = round(sum(float(row.get("amount") or 0) for row in rows if row.get("cost_status") in {"pending_reconciliation", "usage_only", "unavailable"}), 6)
        return {"reserved_cost_eur": residual, "reservation_open": residual > 0}

    def _report(self, job: Dict, progress: int, stage: str, extra=None):
        self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {
            "progress": max(0, min(99, progress)),
            "output": {"stage": stage, **(extra or {})},
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        }, "return=minimal")

    def claim(self, job_id: str = ""):
        function = "claim_job" if job_id else "claim_next_job"
        body = {"p_worker_id": self.worker_id, "p_cloud_execution_id": self.cloud_execution_id}
        if job_id:
            body["p_job_id"] = job_id
        jobs = self.db.rpc(function, body)
        return jobs[0] if jobs else None

    def run_once(self, job_id: str = "") -> bool:
        job = self.claim(job_id)
        if not job:
            return False
        heartbeat = JobHeartbeat(self.db, job["id"], self.worker_id)
        started_monotonic = time.monotonic()
        heartbeat.start()
        try:
            handlers = {
                "collect_sources": self._collect,
                "transform_signals": self._transform_signals,
                "cluster_questions": self._cluster_questions,
                "build_dataset": self._build_dataset,
                "validate_dataset": self._validate_dataset,
                "reverse_engineer": self._reverse_engineer,
            }
            result = handlers[job["kind"]](job)
            runtime_seconds = round(time.monotonic() - started_monotonic, 3)
            self._record_cost(job, "google_cloud", "cloud_run_job", quantity=runtime_seconds, unit="seconds", cost_status="pending_reconciliation", estimated_unit_cost=float(os.getenv("CLOUD_RUN_COST_PER_SECOND_USD", "0.0001")), external_reference=f"{job['id']}:google_cloud:{self.cloud_execution_id}", metadata={"execution_id": self.cloud_execution_id, "cpu": 2, "memory_gib": 2})
            actual_cost, cost_status = self._job_cost_summary(job["id"])
            patch = {"status": "completed", "progress": 100, "output": result if result is not None else {}, "actual_cost_usd": actual_cost, "cost_status": cost_status, **self._settle_reservation(job), "heartbeat_at": datetime.now(timezone.utc).isoformat(), "completed_at": datetime.now(timezone.utc).isoformat()}
            try:
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", patch, "return=minimal")
            except RuntimeError as error:
                if "reservation_open" not in str(error):
                    raise
                # Schéma sans la migration réservation : on clôture quand même,
                # la couverture budgétaire résiduelle reste inactive.
                patch = {key: value for key, value in patch.items() if key not in ("reservation_open", "reserved_cost_eur")}
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", patch, "return=minimal")
        except Exception as error:
            runtime_seconds = round(time.monotonic() - started_monotonic, 3)
            try:
                self._record_cost(job, "google_cloud", "cloud_run_job", quantity=runtime_seconds, unit="seconds", cost_status="pending_reconciliation", estimated_unit_cost=float(os.getenv("CLOUD_RUN_COST_PER_SECOND_USD", "0.0001")), external_reference=f"{job['id']}:google_cloud:{self.cloud_execution_id}", metadata={"execution_id": self.cloud_execution_id, "failed": True, "cpu": 2, "memory_gib": 2})
            except Exception:
                pass
            can_retry = int(job.get("attempt_count", 1)) < int(job.get("max_attempts", 3))
            # Un échec après consommation garde sa provision ; un échec avant
            # toute consommation la libère (résiduel nul).
            settlement = self._settle_reservation(job) if not can_retry else {}
            patch = {"status": "pending" if can_retry else "failed", "error": str(error)[:2000], "output": {}, **settlement, "heartbeat_at": datetime.now(timezone.utc).isoformat(), "completed_at": None if can_retry else datetime.now(timezone.utc).isoformat()}
            try:
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", patch, "return=minimal")
            except RuntimeError as patch_error:
                if "reservation_open" not in str(patch_error):
                    raise
                patch = {key: value for key, value in patch.items() if key not in ("reservation_open", "reserved_cost_eur")}
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", patch, "return=minimal")
            raise
        finally:
            heartbeat.stop()
        return True

    @staticmethod
    def _allocate_source_budgets(sources: list, query_budget: int, sample: bool) -> dict:
        """Répartit un budget maximum par source pour éviter qu'une seule source
        consomme tout le plafond global, surtout en mode échantillon.

        Les réseaux sociaux sont regroupés dans un même pool dont la part totale
        est plafonnée afin d'éviter une explosion du coût lorsque plusieurs
        plateformes sont activées simultanément."""
        if not sample or not sources:
            return {}
        social = {"facebook", "instagram", "linkedin", "x"}
        non_social = [source for source in sources if source not in social]
        social_sources = [source for source in sources if source in social]
        # Cap social pool at 35% of the total query budget when several platforms are active.
        social_pool_share = 0.35 if len(social_sources) > 1 else 0.45
        non_social_budget = int(query_budget * (1 - (social_pool_share if social_sources else 0)))
        social_pool_budget = int(query_budget * social_pool_share) if social_sources else 0
        weights = {"serp": 1.0, "review": 0.7, "forum": 0.8, "reddit": 0.9, "facebook": 0.7, "instagram": 0.7, "linkedin": 0.7, "x": 0.7}
        non_social_weight = sum(weights.get(source, 0.5) for source in non_social) or 1
        social_weight = sum(weights.get(source, 0.5) for source in social_sources) or 1
        result: dict = {}
        for source in non_social:
            result[source] = max(3, int(round(non_social_budget * weights.get(source, 0.5) / non_social_weight)))
        for source in social_sources:
            result[source] = max(1, int(round(social_pool_budget * weights.get(source, 0.5) / social_weight)))
        return result

    def _collect(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        project = self.db.request("GET", "projects", f"select=*&id=eq.{project_id}&limit=1")[0]
        config = neutral_config(project)
        input_config = job.get("input", {})
        budget = clamp_collection_budget(input_config.get("query_budget", 10))
        sample_mode = bool(input_config.get("source_config", {}).get("sample_mode"))
        display_budget_total_eur = float(input_config.get("budget_total_eur") or input_config.get("budget_snapshot", {}).get("total_eur") or 8)
        seed_ids = [str(seed_id) for seed_id in input_config.get("seed_ids", []) if seed_id]
        seed_filter = f"&id=in.({','.join(seed_ids)})" if seed_ids else ""

        def report(progress: int, stage: str, extra=None):
            self._report(job, progress, stage, extra)

        report(3, "Chargement des seeds")
        seed_rows = self.db.request("GET", "seeds", f"select=*&project_id=eq.{project_id}&enabled=eq.true{seed_filter}&order=priority.desc")
        report(8, f"{len(seed_rows)} seeds chargés · préparation des sources")
        config.seeds = deduplicate_seeds(Seed(
            value=row["value"], seed_type=SeedType(row["seed_type"]), priority=row["priority"],
            language=row["language"], market=row["market"], enabled=row["enabled"]
        ) for row in seed_rows)
        requested = set(job.get("input", {}).get("sources", []))

        # En mode échantillon, on borne chaque source pour toucher un peu de tout
        # sans vider le budget dans la première source traitée.
        source_budgets = self._allocate_source_budgets(sorted(requested), budget, sample_mode)
        minimum_source_signals = int(input_config.get("source_config", {}).get("minimum_source_signals", 5))
        config.scraping.serp["query_budget"] = max(minimum_source_signals, source_budgets.get("serp", budget))
        forum_budget = max(source_budgets.get("forum", 0), source_budgets.get("reddit", 0)) or budget
        config.scraping.forum["max_threads"] = max(minimum_source_signals, forum_budget)
        config.scraping.reviews["max_pages"] = max(minimum_source_signals // 4, min(10, source_budgets.get("review", budget)))
        source_config = input_config.get("source_config", {}) if isinstance(input_config.get("source_config"), dict) else {}

        def clean_list(key):
            value = source_config.get(key)
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        def bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
            try:
                raw_value = source_config.get(name)
                value = int(default if raw_value is None or raw_value == "" else raw_value)
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        client_name = str(source_config.get("client_name") or "").strip()
        if client_name:
            config.client.name = client_name
            config.client.slug = slugify(client_name)
            domain = str(source_config.get("domain") or "").strip()
            if domain:
                config.client.website = domain
            variants = clean_list("brand_variants")
            config.brand_variants = list(dict.fromkeys([client_name, *variants]))
            config.themes = clean_list("themes") or config.themes
            config.competitors = clean_list("competitors") or config.competitors
            market = str(source_config.get("market") or "").strip().upper()
            config.markets = [market] if market else config.markets
            accepted_languages = [item.lower() for item in clean_list("languages")]
            config.languages = accepted_languages or config.languages
            config.filters.accepted_languages = config.languages

        forum_config = config.sources.setdefault("forums", {"enabled": True})
        configured_platforms = forum_config.get("platforms", [])
        platforms = []
        if "forum" in requested:
            if "forum_urls" in source_config:
                platforms.extend({
                    "name": urlparse(url).netloc.replace("www.", "") or url,
                    "url": url,
                    "search_method": "google_site",
                } for url in clean_list("forum_urls"))
            else:
                platforms.extend(platform for platform in configured_platforms if platform.get("name") != "reddit")
        # Reddit passe par l'adaptateur gratuit (Arctic Shift + API JSON),
        # plus par Bright Data.
        if "reddit" in requested:
            reddit_social = source_config.get("subreddits")
            subreddits = clean_list("subreddits")
            if not subreddits:
                for platform in configured_platforms:
                    if platform.get("name") == "reddit":
                        subreddits = list(platform.get("subreddits") or [])
            platforms.append({"name": "reddit", "subreddits": subreddits})
            if "forum" not in requested:
                requested.add("forum")
        forum_config["platforms"] = platforms

        if "trustpilot_url" in source_config:
            trustpilot_url = str(source_config.get("trustpilot_url") or "").strip()
            config.sources.setdefault("reviews", {})["platforms"] = [{"name": "trustpilot", "url": trustpilot_url, "method": "api"}] if trustpilot_url else []
        if clean_list("google_maps_queries"):
            config.sources["reviews"]["platforms"].append({"name": "google_reviews", "queries": clean_list("google_maps_queries"), "method": "google_maps_scraper"})
        for key in ("after", "before", "time_filter"):
            if source_config.get(f"reddit_{key}"):
                config.scraping.forum[key] = str(source_config[f"reddit_{key}"])
        if "serp_templates" in source_config:
            config.sources.setdefault("serp", {})["query_templates"] = clean_list("serp_templates")

        # Bright Data est réservé aux plateformes sans alternative gratuite.
        social_platforms = [platform for platform in ("facebook", "instagram", "linkedin", "x") if platform in requested]
        if social_platforms:
            social_post_limit = bounded_int("social_post_limit", 10, 1, 50)
            social_minimum_factor = max(1, minimum_source_signals // max(1, social_post_limit))
            # Hard cap: total social targets across all platforms is bounded by the
            # shared social budget pool. Each platform gets at least 1 target.
            social_pool_budget = min(source_budgets.get(social_platforms[0], budget), 20) if source_budgets else min(budget, 20)
            max_total_social_targets = max(len(social_platforms), min(social_pool_budget, 20))
            max_per_platform = max(1, max_total_social_targets // len(social_platforms))
            max_social_targets = max(social_minimum_factor, max_per_platform)
            social_limits = {
                "targets": bounded_int("social_target_limit", max_social_targets, 1, 20),
                "posts": social_post_limit,
                "comments": bounded_int("social_comment_limit", 0, 0, 20),
            }
            config.sources["social"] = {
                "limits": social_limits,
                "facebook": {"urls": clean_list("facebook_urls"), "dataset_id": str(source_config.get("facebook_dataset_id") or "").strip()},
                "instagram": {"urls": clean_list("instagram_urls"), "dataset_id": str(source_config.get("instagram_dataset_id") or "").strip()},
                "linkedin": {"urls": clean_list("linkedin_urls"), "dataset_id": str(source_config.get("linkedin_dataset_id") or "").strip()},
                "x": {"urls": clean_list("x_urls"), "dataset_id": str(source_config.get("x_dataset_id") or "").strip()},
            }

        scrapers = []
        if "forum" in requested:
            scrapers.append(ForumScraper(config))
        if "serp" in requested:
            scrapers.append(SerpScraper(config))
        if "review" in requested:
            scrapers.append(ReviewScraper(config))
        if social_platforms:
            scrapers.append(SocialScraper(config, social_platforms))

        fractions = {id(scraper): 0.0 for scraper in scrapers}

        def scraper_progress(scraper, processed: int, total: int, detail: str):
            fractions[id(scraper)] = processed / max(total, 1)
            percent = 10 + int(82 * sum(fractions.values()) / max(len(fractions), 1))
            report(percent, detail, {"source_progress": round(processed / max(total, 1), 3)})

        items = []
        source_report = {}
        # Cap each source at ~25% of the total workflow budget for collection.
        source_budget_eur = {source: (display_budget_total_eur * 0.25) / max(len(requested), 1) for source in requested} if display_budget_total_eur else {}
        for scraper in scrapers:
            scraper.progress_callback = lambda processed, total, detail, current=scraper: scraper_progress(current, processed, total, detail)
            before = len(items)
            items.extend(scraper.run())
            if isinstance(scraper, SocialScraper):
                for platform in scraper.platforms:
                    count = sum(1 for item in items[before:] if item.platform == platform)
                    source_report[platform] = {"collected": count, "errors": scraper.platform_errors.get(platform, 0), "budget_eur": round(source_budget_eur.get(platform, 0), 2)}
                    if scraper.skipped.get(platform):
                        source_report[platform]["skipped"] = scraper.skipped[platform]
            else:
                source_report[scraper.source_type] = {"collected": len(items) - before, "errors": scraper.errors_count, "budget_eur": round(source_budget_eur.get(scraper.source_type, 0), 2)}
                # Reddit transite par le ForumScraper (Arctic Shift) : on isole
                # son volume pour un reporting par source fidèle à la sélection.
                if scraper.source_type == "forum" and "reddit" in requested:
                    reddit_count = sum(1 for item in items[before:] if item.platform == "reddit")
                    source_report["reddit"] = {"collected": reddit_count, "errors": 0, "budget_eur": round(source_budget_eur.get("reddit", 0), 2)}
                    source_report["forum"]["collected"] -= reddit_count
        accepted_languages = {language.lower() for language in config.filters.accepted_languages}
        filtered_items = []
        rejected_languages = 0
        for item in items:
            language = str(item.metadata.get("language") or detect_language(f"{item.title or ''}\n{item.raw_text}") or "").lower()
            item.metadata["language"] = language or None
            if accepted_languages and language and language not in accepted_languages:
                rejected_languages += 1
                continue
            filtered_items.append(item)
        items = filtered_items
        report(94, f"Import de {len(items)} signaux collectés", {"language_rejected": rejected_languages})
        dataforseo_cost = sum(float(getattr(scraper, "api_cost_usd", 0)) for scraper in scrapers)
        if dataforseo_cost:
            self._record_cost(job, "dataforseo", "serp_api", amount=dataforseo_cost, quantity=budget, unit="queries", cost_status="actual")
        rows = [{
            "project_id": project_id, "source_type": item.source_type.value, "platform": item.platform,
            "raw_text": item.raw_text, "title": item.title, "url": item.url, "theme": item.theme,
            "brand": item.brand, "language": item.metadata.get("language"), "metadata": item.metadata,
            "content_hash": hashlib.sha256(f"{item.platform}:{item.raw_text.casefold()}".encode()).hexdigest(),
        } for item in items]
        imported = 0
        for start in range(0, len(rows), 200):
            batch = rows[start:start + 200]
            saved = self.db.request("POST", "signals", "on_conflict=project_id,content_hash", batch, "resolution=ignore-duplicates,return=representation")
            imported += len(saved or [])
            report(94 + min(5, int(5 * min(start + len(batch), len(rows)) / max(len(rows), 1))), f"Import des signaux · {min(start + len(batch), len(rows))}/{len(rows)}", {"imported": imported})
        return {"collected": len(rows), "imported": imported, "sources": sorted(requested), "seeds": len(config.seeds), "query_budget": budget, "source_report": source_report, "language_rejected": rejected_languages, "client": config.client.name, "accepted_languages": sorted(accepted_languages)}

    def _transform_signals(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        self._report(job, 3, "Chargement des signaux")
        project = self.db.request("GET", "projects", f"select=language,name,website&id=eq.{project_id}&limit=1")[0]
        signals = self.db.request("GET", "signals", f"select=*&project_id=eq.{project_id}&order=collected_at.asc")
        existing = self.db.request("GET", "questions", f"select=signal_id&project_id=eq.{project_id}&signal_id=not.is.null")
        processed_ids = {row["signal_id"] for row in existing}
        pending = [signal for signal in signals if signal["id"] not in processed_ids]
        self._report(job, 8, f"{len(pending)}/{len(signals)} signaux à transformer")
        processor = None

        def transform(text, title, language):
            nonlocal processor
            processor = processor or OpenAIProcessor()
            return processor.transform(text, title, language)

        questions = signals_to_questions(
            pending,
            project.get("language", "fr"),
            transform,
            lambda processed, total: self._report(job, 10 + int(55 * processed / max(total, 1)), f"Transformation des signaux · {processed}/{total}"),
            client_domain=project.get("website", ""),
            client_names=[project.get("name", "")],
        )
        self._report(job, 68, f"Enregistrement de {len(questions)} questions")
        rows = [{
            "project_id": project_id, "signal_id": question.signal_id, "text": question.text,
            "provenance": question.provenance, "language": question.language,
            "confidence": question.confidence, "metadata": question.metadata,
        } for question in questions]
        saved = self.db.request("POST", "questions", "on_conflict=project_id,signal_id,text", rows, "resolution=ignore-duplicates,return=representation") if rows else []
        self._report(job, 72, f"{len(saved or [])} questions enregistrées")
        result = {"signals": len(signals), "pending": len(pending), "questions": len(saved or [])}
        if job.get("input", {}).get("chain_cluster"):
            self._report(job, 75, "Clustering des questions")
            result["clustering"] = self._cluster_questions({**job, "input": job["input"].get("cluster_config", {}), "progress_start": 75, "progress_end": 98})
        return result

    def _cluster_questions(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        progress_start = int(job.get("input", {}).get("progress_start", 5))
        progress_end = int(job.get("input", {}).get("progress_end", 98))
        self._report(job, progress_start, "Chargement des questions")
        rows = self.db.request("GET", "questions", f"select=*&project_id=eq.{project_id}&order=created_at.asc")
        if not rows:
            return {"questions": 0, "clusters": 0}
        span = max(1, progress_end - progress_start)
        self._report(job, progress_start + int(span * 0.25), f"Embeddings de {len(rows)} questions")
        processor = OpenAIProcessor()
        embeddings = processor.embeddings([row["text"] for row in rows])
        input_config = job.get("input", {})
        self._report(job, progress_start + int(span * 0.55), "Calcul des clusters sémantiques")
        clusters = cluster_questions(rows, embeddings, float(input_config.get("similarity_threshold", 0.82)), int(input_config.get("min_cluster_size", 2)))
        saved_count = 0
        for index, cluster in enumerate(clusters, start=1):
            self._report(job, progress_start + int(span * (0.55 + 0.4 * index / max(len(clusters), 1))), f"Enregistrement des clusters · {index}/{len(clusters)}")
            cluster_rows = self.db.request("POST", "clusters", "on_conflict=project_id,fingerprint", [{
                "project_id": project_id, "label": cluster["label"],
                "representative_question": cluster["representative_question"],
                "question_count": cluster["question_count"], "source_count": cluster["source_count"],
                "is_geo_relevant": cluster["is_geo_relevant"], "fingerprint": cluster["fingerprint"],
            }], "resolution=merge-duplicates,return=representation")
            cluster_id = cluster_rows[0]["id"]
            self.db.request("DELETE", "cluster_questions", f"cluster_id=eq.{cluster_id}", prefer="return=minimal")
            self.db.request("POST", "cluster_questions", body=[{
                "cluster_id": cluster_id, "question_id": member["question_id"], "similarity": member["similarity"],
            } for member in cluster["members"]])
            saved_count += 1
        return {"questions": len(rows), "clusters": saved_count, "geo_relevant": sum(cluster["is_geo_relevant"] for cluster in clusters), "corporate_excluded": sum(not cluster["is_geo_relevant"] and cluster["question_count"] >= int(input_config.get("min_cluster_size", 2)) for cluster in clusters), "singletons_admitted": sum(cluster["is_geo_relevant"] and cluster["question_count"] == 1 for cluster in clusters)}

    def _build_dataset(self, job: Dict) -> Dict:
        dataset_id = job["input"]["dataset_id"]
        dataset = self.db.request("GET", "datasets", f"select=*&id=eq.{dataset_id}&limit=1")[0]
        project_id = dataset["project_id"]
        if project_id != job["project_id"]:
            raise ValueError("Dataset does not belong to job project")
        self._report(job, 2, "Chargement des clusters")
        cluster_rows = self.db.request("GET", "clusters", f"select=*&project_id=eq.{project_id}&is_geo_relevant=eq.true&order=question_count.desc")
        if not cluster_rows:
            raise RuntimeError("Aucun cluster GEO exploitable. Lancez d'abord le clustering.")
        links = self.db.request("GET", "cluster_questions", "select=cluster_id,questions(text,provenance)")
        questions_by_cluster = {}
        provenance_by_text = {}
        cluster_ids = {row["id"] for row in cluster_rows}
        for link in links:
            question = link.get("questions") or {}
            if link["cluster_id"] in cluster_ids and question.get("text"):
                questions_by_cluster.setdefault(link["cluster_id"], []).append(
                    {"text": question["text"], "provenance": question.get("provenance", "observed")})
                provenance_by_text[" ".join(question["text"].casefold().split())] = question.get("provenance", "observed")
        language = self.db.request("GET", "projects", f"select=language,country&id=eq.{project_id}&limit=1")[0]
        build_config = dataset.get("build_config", {})
        clusters = [ClusterInput(
            id=row["id"], label=row["label"], representative_question=row["representative_question"],
            questions=questions_by_cluster.get(row["id"], []), language=language.get("language", "fr"),
            question_count=row.get("question_count", 0), source_count=row.get("source_count", 0),
            representative_provenance=provenance_by_text.get(" ".join(row["representative_question"].casefold().split()), "observed"),
        ) for row in cluster_rows]
        project = self.db.request("GET", "projects", f"select=name&id=eq.{project_id}&limit=1")[0]
        self._report(job, 5, f"Construction des candidats depuis {len(clusters)} clusters")
        built = score_candidates(DatasetBuilder().build(clusters, DatasetBuildConfig(
            mode=build_config.get("mode", "faithful"),
            intent_similarity_threshold=float(build_config.get("intent_similarity_threshold", 0.65)),
            personas=build_config.get("personas", []), stages=build_config.get("stages", ["discovery", "comparison"]),
            specificity_levels=build_config.get("specificity_levels", [0, 1, 2]),
            candidates_per_cluster=build_config.get("candidates_per_cluster", 9),
            brand_name=str(build_config.get("brand_name") or project.get("name", "")),
        )))
        # The global pool cap follows the same intent-first rule as every
        # other cap: representatives of every intent first, variants last —
        # truncating in cluster order would drop a whole need.
        pool_size = int(dataset.get("candidate_pool_size", dataset["target_size"]))
        candidates = intent_first_order(built)[:pool_size]
        if not candidates:
            raise RuntimeError("Aucun candidat généré. Vérifiez le nom du projet / marque ou les clusters.")
        # Qualification : catégorie, thème kickoff, justification — sur les
        # candidats réels, depuis la config kickoff de la dernière collecte.
        collect_jobs = self.db.request("GET", "jobs", f"select=input&project_id=eq.{project_id}&kind=eq.collect_sources&order=created_at.desc&limit=1")
        source_config = (collect_jobs[0].get("input", {}) or {}).get("source_config", {}) if collect_jobs else {}
        brand_variants = [build_config.get("brand_name") or project.get("name", ""), *source_config.get("brand_variants", [])]
        competitors = source_config.get("competitors", [])
        kickoff_themes = source_config.get("themes", [])
        for candidate in candidates:
            candidate.metadata["qualification"] = qualify_question(candidate.text, brand_variants, competitors, kickoff_themes)
        covered_themes = {c.metadata["qualification"].get("kickoff_theme") for c in candidates}
        covered_themes.discard("")
        themes_uncovered = [theme for theme in kickoff_themes if theme not in covered_themes]
        sample_size = int(dataset.get("execution_sample_size", len(candidates)))
        max_per_cluster = int(build_config.get("max_per_cluster", 5))
        selected, category_deficits = select_with_quotas(candidates, sample_size, stratified_sample, max_per_cluster=max_per_cluster)
        selected_ids = {candidate.id for candidate in selected}
        if not selected_ids:
            raise RuntimeError("Aucun candidat sélectionné pour l'exécution. Vérifiez la taille de l'échantillon.")
        repetitions = int(dataset["repetitions"])
        engines = dataset.get("engines", ["chatgpt"])
        cost = estimate_cost(len(selected), repetitions, len(engines), float(dataset.get("cost_per_execution_eur", 0)))
        if cost["estimated_cost_eur"] > float(dataset.get("max_budget_eur", 0)):
            raise RuntimeError(f"Estimated cost {cost['estimated_cost_eur']:.2f} EUR exceeds budget")
        self._report(job, 8, f"{len(candidates)} candidats · {len(selected)} sélectionnés · {cost['executions']} exécutions prévues")
        prompt_payload = [{
            "project_id": project_id, "cluster_id": candidate.source_reference, "text": candidate.text,
            "provenance": candidate.provenance.value, "confidence": candidate.confidence,
            "status": "testing" if candidate.id in selected_ids else "draft",
            "expected_fan_outs": candidate.expected_fan_outs, "metadata": candidate.metadata,
        } for candidate in candidates]
        if prompt_payload:
            self.db.request("POST", "prompts", "on_conflict=project_id,text", prompt_payload, "resolution=ignore-duplicates,return=minimal")
        prompt_rows = self.db.request("GET", "prompts", f"select=*&project_id=eq.{project_id}")
        prompts_by_text = {prompt["text"]: prompt for prompt in prompt_rows}
        example_payload = [{
            "dataset_id": dataset_id, "prompt_id": prompts_by_text[candidate.text]["id"], "cluster_id": prompts_by_text[candidate.text]["cluster_id"],
            "status": "executing" if candidate.id in selected_ids else "candidate",
            "persona": candidate.metadata.get("persona"), "journey_stage": candidate.metadata.get("stage"),
            "specificity_level": candidate.metadata.get("specificity_level"),
            "expected_sub_intents": candidate.expected_fan_outs,
            "pre_execution_score": candidate.confidence,
            "selected_for_execution": candidate.id in selected_ids,
            "selection_reason": "stratified_screening" if candidate.id in selected_ids else "candidate_pool",
            "validation_tier": 3, "target_runs": repetitions,
        } for candidate in candidates if candidate.text in prompts_by_text]
        if example_payload:
            self.db.request("POST", "dataset_examples", "on_conflict=dataset_id,prompt_id", example_payload, "resolution=ignore-duplicates,return=minimal")
        examples = self.db.request("GET", "dataset_examples", f"select=*&dataset_id=eq.{dataset_id}")
        examples_by_prompt = {example["prompt_id"]: example for example in examples}
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "executing", "estimated_cost_eur": cost["estimated_cost_eur"]}, "return=minimal")
        self._report(job, 10, "Démarrage des exécutions moteur")
        provider_name = os.getenv("DATASET_PROVIDER", "brightdata")
        # Auxiliary fan-out re-executions can be disabled per dataset; they are
        # billed OpenAI calls, never part of the main screening pass.
        self.fanout_fallback_enabled = bool(build_config.get("fanout_fallback", getattr(self, "fanout_fallback_enabled", True)))
        if provider_name == "dataforseo":
            provider = DataForSEOProvider()
        elif provider_name == "openai":
            provider = OpenAILLMProvider()
        elif provider_name == "oxylabs":
            provider = OxylabsProvider()
        else:
            provider = BrightDataProvider()
        bright_cost_before = self._brightdata_account_cost() if provider_name == "brightdata" else None
        threshold = float(build_config.get("quality_threshold", 0.65))
        records = []
        accepted = rejected = completed = openai_search_calls = 0
        tasks = []
        stored_observations = {}
        duplicate_texts_skipped = 0
        observations_reused = 0
        seen_texts = set()
        all_prompts = [candidate.text for candidate in candidates]
        for candidate in selected:
            normalized = " ".join(candidate.text.casefold().split())
            if normalized in seen_texts:
                duplicate_texts_skipped += 1
                continue
            seen_texts.add(normalized)
            prompt = prompts_by_text.get(candidate.text)
            example = examples_by_prompt.get(prompt["id"]) if prompt else None
            if not prompt or not example:
                continue
            existing = self._stored_observations(prompt["id"], engines)
            observations_reused += len(existing)
            stored_observations[example["id"]] = existing
            if int(example.get("completed_runs") or 0) >= repetitions or min(sum(item.engine == engine for item in existing) for engine in engines) >= repetitions:
                if example.get("status") in ("accepted", "rejected"):
                    accepted += int(example.get("status") == "accepted")
                    rejected += int(example.get("status") == "rejected")
                elif existing:
                    scores = score_dataset_example(candidate, existing, all_prompts)
                    is_accepted = scores["quality_score"] >= threshold
                    accepted += int(is_accepted)
                    rejected += int(not is_accepted)
                    self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {"status": "accepted" if is_accepted else "rejected", **EXAMPLE_SCORE_COLUMNS(scores), "completed_runs": repetitions, "rejection_reason": None if is_accepted else "quality_below_threshold"}, "return=minimal")
                    self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}", {"status": "validated" if is_accepted else "archived", "confidence": scores["quality_score"]}, "return=minimal")
                continue
            records.append((candidate, prompt, example, existing))
            for engine in engines:
                completed_runs = sum(item.engine == engine for item in existing)
                for run_index in range(completed_runs, repetitions):
                    tasks.append((candidate, prompt, example, engine, run_index))
        openai_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        total = max(1, len(tasks))
        expected = {example["id"]: repetitions * len(engines) for _, _, example, _ in records}
        received = {example["id"]: 0 for _, _, example, _ in records}
        concurrency = max(1, min(20, int(os.getenv("ANALYSIS_CONCURRENCY", "10"))))
        self._report(job, 12, f"{len(tasks)} exécutions à lancer (provider={provider_name}, concurrency={concurrency})")
        if not tasks and not (accepted or rejected):
            raise RuntimeError(f"Aucune exécution à lancer. {len(records)} exemples existants déjà complétés ou manquants.")
        # For providers that support batched execution (Bright Data), group tasks
        # by engine to send several prompts in a single snapshot.
        if provider_name == "brightdata":
            records_by_engine = {}
            for candidate, prompt, example, engine, run_index in tasks:
                records_by_engine.setdefault(engine, []).append((candidate, prompt, example, run_index))
            batch_size = getattr(provider, "batch_size", 10)
            for engine, engine_tasks in records_by_engine.items():
                self._report(job, 15, f"Moteur {engine}: {len(engine_tasks)} tâches, batch size {batch_size}")
                for start in range(0, len(engine_tasks), batch_size):
                    batch = engine_tasks[start:start + batch_size]
                    requests = [AnalysisRequest(prompt=candidate.text, engine=engine, country=language.get("country", "BE"), language=language.get("language", "fr"), metadata={"example_id": example["id"], "run_index": run_index, "phase": "build"}) for candidate, prompt, example, run_index in batch]
                    self._report(job, 15 + int(75 * completed / total), f"Envoi batch {engine} ({len(requests)} prompts)")
                    observations = self._execute_analysis_batch(provider, requests)
                    self._report(job, 15 + int(75 * completed / total), f"Batch {engine} reçu: {len(observations)} observations")
                    if len(observations) != len(batch):
                        raise RuntimeError(f"Batch {engine}: {len(observations)} observations pour {len(batch)} requêtes")
                    for (candidate, prompt, example, run_index), observation in zip(batch, observations):
                        self._persist_observation(prompt, observation, job=job)
                        stored_observations[example["id"]].append(observation)
                        received[example["id"]] += 1
                        openai_search_calls += int(bool(observation.metadata.get("reexecution_observation_id")))
                        completed += 1
                        if len(stored_observations[example["id"]]) == expected[example["id"]]:
                            scores = score_dataset_example(candidate, stored_observations[example["id"]], all_prompts)
                            is_accepted = scores["quality_score"] >= threshold
                            accepted += int(is_accepted)
                            rejected += int(not is_accepted)
                            self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {"status": "accepted" if is_accepted else "rejected", **EXAMPLE_SCORE_COLUMNS(scores), "completed_runs": repetitions, "rejection_reason": None if is_accepted else "quality_below_threshold"}, "return=minimal")
                            self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}", {"status": "validated" if is_accepted else "archived", "confidence": scores["quality_score"]}, "return=minimal")
                        self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": min(95, 10 + int(85 * completed / total))}, "return=minimal")
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(self._run_once, provider, candidate, example, engine, run_index, language, "build"): (candidate, prompt, example) for candidate, prompt, example, engine, run_index in tasks}
                for future in as_completed(futures):
                    candidate, prompt, example = futures[future]
                    observation = future.result()
                    self._persist_observation(prompt, observation, job=job)
                    stored_observations[example["id"]].append(observation)
                    received[example["id"]] += 1
                    openai_search_calls += int(bool(observation.metadata.get("reexecution_observation_id")))
                    completed += 1
                    if len(stored_observations[example["id"]]) == expected[example["id"]]:
                        scores = score_dataset_example(candidate, stored_observations[example["id"]], all_prompts)
                        is_accepted = scores["quality_score"] >= threshold
                        accepted += int(is_accepted)
                        rejected += int(not is_accepted)
                        self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {"status": "accepted" if is_accepted else "rejected", **EXAMPLE_SCORE_COLUMNS(scores), "completed_runs": repetitions, "rejection_reason": None if is_accepted else "quality_below_threshold"}, "return=minimal")
                        self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}", {"status": "validated" if is_accepted else "archived", "confidence": scores["quality_score"]}, "return=minimal")
                    self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": min(95, 10 + int(85 * completed / total))}, "return=minimal")
        if completed == 0 and not (accepted or rejected):
            raise RuntimeError("Aucune observation n'a été produite. Vérifiez les clés API et le provider.")
        if openai_search_calls:
            self._record_cost(job, "openai", "web_search", quantity=openai_search_calls, unit="calls", cost_status="usage_only", estimated_unit_cost=float(os.getenv("OPENAI_SEARCH_CALL_COST_USD", "0.03")), metadata=openai_usage, dataset_id=dataset_id)
        bright_delta = None
        if provider_name == "brightdata":
            bright_cost_after = self._brightdata_account_cost()
            if bright_cost_before is not None and bright_cost_after is not None and bright_cost_after > bright_cost_before:
                bright_delta = round(bright_cost_after - bright_cost_before, 6)
                self._record_cost(job, "brightdata", "web_scraper_api", amount=bright_delta, quantity=completed, unit="records", cost_status="account_delta", metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
            else:
                self._record_cost(job, "brightdata", "web_scraper_api", quantity=completed, unit="records", cost_status="pending_reconciliation", estimated_unit_cost=float(dataset.get("cost_per_execution_eur") or 0.05), metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
        # Intent inventory recorded before every cap: the coverage denominator
        # must be the admissible intents identified, not only the intents that
        # survived selection. Deferred intents and exclusion reasons stay
        # visible for the justification table.
        intent_inventory = sorted({
            intent_id
            for c in built
            for intent_id in (list(c.metadata.get("cluster_intent_ids") or []) or ([c.metadata.get("intent_id")] if c.metadata.get("intent_id") else []))
        })
        intents_selected = sorted({str(c.metadata.get("intent_id")) for c in selected if c.metadata.get("intent_id")})
        statistics = {"candidates": len(candidates), "sampled": len(selected), "accepted": accepted, "rejected": rejected, "executions": completed, "concurrency": concurrency, "estimated_cost_eur": cost["estimated_cost_eur"], "confirmed_brightdata_cost_usd": bright_delta, "acceptance_rate": round(accepted / len(selected), 4) if selected else 0,
            "execution_provider": provider_name,
            "execution_target": int(dataset.get("execution_sample_size", len(candidates))),
            "clusters_available": len(clusters),
            "auxiliary_openai_calls": openai_search_calls,
            "duplicate_texts_skipped": duplicate_texts_skipped,
            "category_counts": {name: sum(1 for c in candidates if c.metadata.get("qualification", {}).get("category") in (names if isinstance(names, tuple) else (names,))) for name, names in {"brand": "brand", "comparaison_standard": "comparaison_standard", "non_brand_kickoff": "non_brand_kickoff", "hors_périmètre": "hors_périmètre"}.items()},
            "category_selected": {name: sum(1 for c in selected if c.metadata.get("qualification", {}).get("category") == name) for name in ("brand", "comparaison_standard", "non_brand_kickoff", "hors_périmètre")},
            "category_deficits": category_deficits,
            "themes_uncovered": themes_uncovered,
            "observations_reused": observations_reused,
            "fanout_fallback": getattr(self, "fanout_fallback_enabled", True),
            "worker_version": os.getenv("WORKER_VERSION") or os.getenv("GIT_SHA") or "unknown",
            "intents_identified": intent_inventory,
            "intents_selected": intents_selected,
            "intents_deferred": [i for i in intent_inventory if i not in intents_selected],
            "exclusion_reasons": {"brand_filter": "clusters écartés avant construction" if len(clusters) != len(set(c.source_reference for c in built)) else None, "pool_cap": f"pool_size={pool_size}" if len(built) > pool_size else None}}
        confirmed_cost = bright_delta or 0
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "ready", "statistics": statistics, "actual_cost_usd": confirmed_cost, "cost_status": "partial" if openai_search_calls else "reconciled", "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
        self._report(job, 99, f"Dataset prêt: {accepted} acceptés, {rejected} rejetés, {completed} exécutions")
        return statistics

    def _validate_dataset(self, job: Dict) -> Dict:
        dataset_id = job["input"]["dataset_id"]
        target_runs = int(job["input"].get("target_runs", 3))
        limit = int(job["input"].get("limit", 100))
        dataset = self.db.request("GET", "datasets", f"select=*&id=eq.{dataset_id}&limit=1")[0]
        if dataset["project_id"] != job["project_id"]:
            raise ValueError("Dataset does not belong to job project")
        examples = self.db.request("GET", "dataset_examples", f"select=*&dataset_id=eq.{dataset_id}&status=eq.accepted&completed_runs=lt.{target_runs}&order=quality_score.desc&limit={limit}")
        if not examples:
            return {"selected": 0, "executions": 0, "target_runs": target_runs}
        prompt_ids = [example["prompt_id"] for example in examples]
        prompt_rows = self.db.request("GET", "prompts", f"select=*&id=in.({','.join(prompt_ids)})")
        prompts = {prompt["id"]: prompt for prompt in prompt_rows}
        project = self.db.request("GET", "projects", f"select=language,country&id=eq.{dataset['project_id']}&limit=1")[0]
        engines = dataset.get("engines", ["chatgpt"])
        records = []
        tasks = []
        stored_observations = {}
        for example in examples:
            prompt = prompts[example["prompt_id"]]
            # Execute the current version: an edited text is the formulation
            # under test; the original prompt keeps its historical runs.
            executed_text = (example.get("edited_prompt_text") or prompt["text"]).strip()
            candidate = PromptCandidate(text=executed_text, provenance=PromptProvenance(prompt["provenance"]), source_reference=prompt.get("cluster_id") or "", expected_fan_outs=prompt.get("expected_fan_outs", []), metadata=prompt.get("metadata", {}))
            existing = self._stored_observations(prompt["id"], engines)
            if example.get("edited_prompt_text"):
                # Only runs of this exact version count towards its target;
                # the previous version's observations are history, not proof.
                existing = [item for item in existing if item.raw_response.get("executed_text") == example["edited_prompt_text"]]
            stored_observations[example["id"]] = existing
            records.append((candidate, prompt, example, existing))
            for engine in engines:
                completed_runs = sum(item.engine == engine for item in existing)
                for run_index in range(completed_runs, target_runs):
                    tasks.append((candidate, prompt, example, engine, run_index))
        additional_executions = len(tasks)
        additional_cost = additional_executions * float(dataset.get("cost_per_execution_eur", 0))
        projected_cost = float(dataset.get("estimated_cost_eur", 0)) + additional_cost
        if projected_cost > float(dataset.get("max_budget_eur", 0)):
            raise RuntimeError(f"Projected cost {projected_cost:.2f} EUR exceeds budget")
        provider_name = os.getenv("DATASET_PROVIDER", "brightdata")
        if provider_name == "dataforseo":
            provider = DataForSEOProvider()
        elif provider_name == "openai":
            provider = OpenAILLMProvider()
        elif provider_name == "oxylabs":
            provider = OxylabsProvider()
        else:
            provider = BrightDataProvider()
        bright_cost_before = self._brightdata_account_cost() if provider_name == "brightdata" else None
        completed = openai_search_calls = 0
        openai_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        concurrency = max(1, min(20, int(os.getenv("ANALYSIS_CONCURRENCY", "10"))))
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(self._run_once, provider, candidate, example, engine, run_index, project, "validation"): (candidate, prompt, example) for candidate, prompt, example, engine, run_index in tasks}
            for future in as_completed(futures):
                candidate, prompt, example = futures[future]
                observation = future.result()
                self._persist_observation(prompt, observation, job=job)
                stored_observations[example["id"]].append(observation)
                openai_search_calls += int(bool(observation.metadata.get("reexecution_observation_id")))
                completed += 1
                if min(sum(item.engine == engine for item in stored_observations[example["id"]]) for engine in engines) >= target_runs:
                    scores = score_dataset_example(candidate, stored_observations[example["id"]])
                    self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {**EXAMPLE_SCORE_COLUMNS(scores), "target_runs": target_runs, "completed_runs": target_runs, "validation_tier": 1 if target_runs == 5 else 2}, "return=minimal")
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": min(95, 10 + int(85 * completed / max(1, additional_executions)))}, "return=minimal")
        if openai_search_calls:
            self._record_cost(job, "openai", "web_search", quantity=openai_search_calls, unit="calls", cost_status="usage_only", estimated_unit_cost=float(os.getenv("OPENAI_SEARCH_CALL_COST_USD", "0.03")), metadata=openai_usage, dataset_id=dataset_id)
        bright_delta = None
        if provider_name == "brightdata":
            bright_cost_after = self._brightdata_account_cost()
            if bright_cost_before is not None and bright_cost_after is not None and bright_cost_after > bright_cost_before:
                bright_delta = round(bright_cost_after - bright_cost_before, 6)
                self._record_cost(job, "brightdata", "web_scraper_api", amount=bright_delta, quantity=completed, unit="records", cost_status="account_delta", metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
            else:
                self._record_cost(job, "brightdata", "web_scraper_api", quantity=completed, unit="records", cost_status="pending_reconciliation", estimated_unit_cost=float(dataset.get("cost_per_execution_eur") or 0.05), metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
        confirmed_cost = float(dataset.get("actual_cost_usd", 0)) + (bright_delta or 0)
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"estimated_cost_eur": round(projected_cost, 2), "actual_cost_usd": round(confirmed_cost, 6), "cost_status": "partial" if openai_search_calls else "reconciled"}, "return=minimal")
        return {"selected": len(examples), "executions": completed, "concurrency": concurrency, "target_runs": target_runs, "additional_cost_eur": round(additional_cost, 2), "confirmed_brightdata_cost_usd": bright_delta}

    def _reverse_engineer(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        accepted = self.db.request("GET", "dataset_examples", "select=prompt_id&status=eq.accepted")
        accepted_prompt_ids = {row["prompt_id"] for row in accepted}
        prompts = self.db.request("GET", "prompts", f"select=id,text&project_id=eq.{project_id}")
        prompts_by_id = {row["id"]: row for row in prompts if row["id"] in accepted_prompt_ids}
        if not prompts_by_id:
            return {"examples": 0, "reconstructed": 0}
        # Same admission contract as the corpus export and the target selector:
        # non-empty answer, no provider error, Bright Data execution only.
        observations = self.db.request("GET", "observations", f"select=id,prompt_id,engine,provider,answer,raw_response&prompt_id=in.({','.join(prompts_by_id)})")
        observations = [row for row in observations if row.get("provider") in ELIGIBLE_PROVIDERS
            and str(row.get("answer") or "").strip() and not (row.get("raw_response") or {}).get("error")]
        observation_ref = {row["id"]: row for row in observations}
        fan_out_rows = self.db.request("GET", "fan_outs", f"select=observation_id,query,source&observation_id=in.({','.join(observation_ref)})") if observations else []
        # Examples are segmented by engine: ChatGPT traces never mix with
        # Gemini traces in the same ICL context, and only same-run traces count.
        fan_outs_by_key = {}
        for row in fan_out_rows:
            observation = observation_ref.get(row["observation_id"])
            if observation and row.get("source") == same_run_fan_out_source(observation.get("provider"), observation.get("engine")):
                # The example prompt is the exact text executed for that run:
                # an edited version produces its own couples, never merged
                # with the previous version's traces.
                executed_text = str((observation.get("raw_response") or {}).get("executed_text") or prompts_by_id[observation["prompt_id"]]["text"])
                key = (observation["prompt_id"], executed_text, str(observation.get("engine") or ""))
                fan_outs_by_key.setdefault(key, []).append(row["query"])
        examples = [ReconstructionExample(executed_text, fan_outs, prompt_id, engine)
            for (prompt_id, executed_text, engine), fan_outs in fan_outs_by_key.items() if fan_outs]
        if not examples:
            return {"examples": 0, "reconstructed": 0,
                "skipped": "No same-run provider-reported traces on this surface; reconstruction unavailable"}
        reconstructor = ICLPromptReconstructor(examples)
        if not reconstructor.icl_available:
            raise RuntimeError("OPENAI_API_KEY and observed examples are required for ICL; use build_dataset for generation from user signals")
        project = self.db.request("GET", "projects", f"select=language,country&id=eq.{project_id}&limit=1")[0]
        options = job.get("input") or {}
        # Only persisted observations belonging to this project can be targets.
        target_ids = options.get("target_observation_ids") or []
        if not target_ids:
            return {"examples": len(examples), "reconstructed": 0, "skipped": "No observed targets selected; use build_dataset for signal-based generation"}
        project_prompts = self.db.request("GET", "prompts", f"select=id,cluster_id,text&project_id=eq.{project_id}")
        owned = {row["id"]: row for row in project_prompts}
        candidates_targets = self.db.request("GET", "observations", f"select=id,prompt_id,engine,provider,answer,raw_response->>error,raw_response->>executed_text&prompt_id=in.({','.join(owned)})") if owned else []
        owned_ids = {row["id"] for row in candidates_targets}
        if not set(target_ids) <= owned_ids:
            raise ValueError("Target observations must belong to this project")
        # Admission contract: valid trace only (non-empty answer, no provider
        # error, Bright Data execution). Ineligible selections are skipped.
        # NB: `raw_response->>error` is projected flat as `error`.
        targets = [row for row in candidates_targets if row["id"] in target_ids
            and row.get("provider") in ELIGIBLE_PROVIDERS and str(row.get("answer") or "").strip()
            and not row.get("error")]
        max_candidates = max(3, min(5, int(options.get("max_candidates_per_cluster", 3))))
        max_targets = max(1, min(10, int(options.get("max_targets", 1))))
        runs = max(1, min(4, int(options.get("validation_runs", 1))))
        # Paid validation is bounded and opt-in with a declared execution ceiling.
        execution_limit = int(options.get("max_validation_executions", 0))
        if execution_limit < min(len(targets), max_targets) * max_candidates * runs:
            raise ValueError("Set max_validation_executions to cover the bounded reconstruction validation plan")
        provider = BrightDataProvider()
        scorer = semantic_scorer()
        threshold = float(options.get("reproduction_threshold", 0.65))
        saved_count = executions = validated = 0
        held_out_rows = []

        def execute_once(prompt, candidate, engine, run_index, parent_observation_id=None):
            nonlocal executions
            # No secondary-engine fan-outs: reproduction must come from the
            # target's real surface (Bright Data engine, or the OpenAI web
            # search surface for re-execution targets).
            request = AnalysisRequest(candidate.text, engine=engine,
                country=project.get("country", "BE"), language=project.get("language", "fr"))
            if engine == "openai_web_search":
                if not self.fanout_extractor:
                    raise RuntimeError("OPENAI_API_KEY is required to validate openai_web_search targets")
                extracted = self.fanout_extractor.extract(request)
                observation = AnalysisObservation(candidate.text, "openai", "openai_web_search",
                    answer=extracted.get("answer") or "", fan_outs=extracted["queries"],
                    country=request.country, language=request.language, model=extracted["model"],
                    web_search_triggered=True,
                    raw_response={"response_id": extracted["response_id"], "relation": "independent_reexecution",
                        "search_calls": extracted["search_calls"], "usage": extracted["usage"]})
                observation.metadata["fan_out_source"] = "openai_responses_web_search"
                self._persist_observation(prompt, observation, job=job, parent_observation_id=parent_observation_id)
                executions += 1
                self._record_cost(job, "openai", "reconstruction_validation", quantity=1, unit="executions",
                    cost_status="pending_reconciliation", estimated_unit_cost=float(options.get("cost_per_execution_eur", 0.05)),
                    external_reference=f"{job['id']}:{prompt['id']}:{run_index}")
                return observation
            observation = self._execute_analysis(provider, request)
            self._persist_observation(prompt, observation, job=job, parent_observation_id=parent_observation_id)
            executions += 1
            self._record_cost(job, "brightdata", "reconstruction_validation", quantity=1, unit="executions",
                cost_status="pending_reconciliation", estimated_unit_cost=float(options.get("cost_per_execution_eur", 0.05)),
                external_reference=f"{job['id']}:{prompt['id']}:{run_index}")
            return observation

        for target in targets[:max_targets]:
            if executions >= execution_limit:
                break
            query_rows = self.db.request("GET", "fan_outs", f"select=query,source&observation_id=eq.{target['id']}&order=position.asc")
            expected_source = same_run_fan_out_source(target.get("provider"), target.get("engine"))
            queries = list(dict.fromkeys(row["query"] for row in query_rows if row.get("query") and row.get("source") == expected_source))
            if not queries:
                continue
            # Hold out the original prompt and its near-variants: they must not
            # leak into the ICL context of the reconstruction target. Context is
            # restricted to traces from the same engine as the target.
            target_signature = build_signature([str(target.get("executed_text") or owned[target["prompt_id"]].get("text", ""))])
            reconstructor.examples = [e for e in examples if e.source_reference != target["prompt_id"]
                and e.engine == str(target.get("engine") or "")
                and signature_similarity(target_signature, build_signature([e.prompt])) < 0.8]
            if not reconstructor.icl_available:
                continue
            pending = []
            for candidate in reconstructor.reconstruct(queries, project.get("language", "fr"), max_candidates):
                if candidate.metadata.get("method") != "icl_retrieval":
                    raise RuntimeError("ICL generation failed; deterministic fallback is not accepted by this job")
                metadata = {**candidate.metadata, "target_observation_id": target["id"], "target_engine": target["engine"]}
                rows = self.db.request("POST", "prompts", "on_conflict=project_id,text", [{
                    "project_id": project_id, "cluster_id": owned[target["prompt_id"]].get("cluster_id"),
                    "text": candidate.text, "provenance": "reverse_engineered", "confidence": candidate.confidence,
                    "status": "testing", "expected_fan_outs": queries, "metadata": metadata,
                }], "resolution=ignore-duplicates,return=representation")
                if rows:
                    pending.append({"candidate": candidate, "prompt": rows[0], "metadata": metadata, "observations": []})
            # Adaptive validation: one run per candidate first, extra runs only
            # for candidates that reproduce the target fan-outs.
            for entry in pending:
                if executions >= execution_limit:
                    break
                entry["observations"].append(execute_once(entry["prompt"], entry["candidate"], target["engine"], 0, parent_observation_id=target["id"]))
                entry["passed_first"] = (bool(entry["observations"][0].fan_outs)
                    and not entry["observations"][0].raw_response.get("error")
                    and score_dataset_example(entry["candidate"], entry["observations"], semantic_scorer=scorer)["reproduction_score"] >= threshold)
            for entry in [e for e in pending if e["passed_first"]]:
                while len(entry["observations"]) < runs and executions < execution_limit:
                    entry["observations"].append(execute_once(entry["prompt"], entry["candidate"], target["engine"], len(entry["observations"]), parent_observation_id=target["id"]))
            for entry in pending:
                candidate, prompt, metadata = entry["candidate"], entry["prompt"], entry["metadata"]
                observations = entry["observations"]
                if not observations:
                    continue
                run_count = len(observations)
                scores = score_dataset_example(candidate, observations, semantic_scorer=scorer)
                passed = (all(o.fan_outs and not o.raw_response.get("error") for o in observations)
                    and scores["reproduction_score"] >= threshold)
                # A single run establishes reproduction, not stability.
                final_status = "validated" if passed and run_count >= 3 and (scores["stability_score"] or 0.0) >= 0.65 else "draft"
                metadata.update({**scores, "validation_runs": run_count, "reproduction_passed": passed,
                    "stability_measured": run_count >= 2, "adaptive_validation": True})
                self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}&project_id=eq.{project_id}",
                    {"status": final_status, "confidence": scores["reproduction_score"], "metadata": metadata}, "return=minimal")
                validated += int(final_status == "validated")
                saved_count += 1
            # §8 baseline: the nearest admissible corpus prompt is executed
            # once on the same surface, under the same bounded plan, so ICL is
            # compared to a trivially strong alternative — never claimed better
            # without paired results.
            icl_row = {"target_id": target["id"], "icl_candidates": [], "baseline_candidates": [], "observed_queries": queries}
            for entry in pending:
                icl_row["icl_candidates"].append({
                    "prompt": entry["candidate"].text,
                    "observed_queries": entry["observations"][0].fan_outs if entry["observations"] else None,
                })
            baseline_text = nearest_baseline(queries, reconstructor.examples, target_prompt=owned[target["prompt_id"]].get("text", ""))
            if baseline_text and executions < execution_limit:
                baseline_prompt = next((p for p in owned.values() if p.get("text") == baseline_text), None)
                if baseline_prompt:
                    baseline_candidate = PromptCandidate(text=baseline_text, provenance=PromptProvenance.REVERSE_ENGINEERED,
                        source_reference=target["id"], confidence=0.0, expected_fan_outs=queries,
                        metadata={"method": "nearest_baseline", "target_observation_id": target["id"]})
                    baseline_observation = execute_once(baseline_prompt, baseline_candidate, target["engine"], 0, parent_observation_id=target["id"])
                    icl_row["baseline_candidates"].append({"prompt": baseline_text, "observed_queries": baseline_observation.fan_outs or None})
            held_out_rows.append(HeldOutTarget(
                target_id=target["id"], observed_queries=queries,
                icl_candidates=icl_row["icl_candidates"], baseline_candidates=icl_row["baseline_candidates"]))
        result = {"examples": len(examples), "reconstructed": saved_count, "executions": executions, "validated": validated}
        if held_out_rows:
            result["baseline_evaluation"] = evaluate_held_out(held_out_rows, threshold=threshold)
        return result


def main():
    parser = argparse.ArgumentParser(description="Run Prompt Lab collection jobs")
    parser.add_argument("--config", default="config/decathlon.yaml")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--job-id", default=os.getenv("JOB_ID", ""))
    parser.add_argument("--worker-id", default=os.getenv("WORKER_ID", ""))
    args = parser.parse_args()
    worker = CollectionWorker(args.config, args.worker_id)
    if args.once or args.job_id:
        worker.run_once(args.job_id)
        return
    while worker.run_once():
        pass


if __name__ == "__main__":
    main()
