#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder
from analysis.dataset_quality import score_dataset_example
from analysis.dataset_funnel import estimate_cost, score_candidates, stratified_sample
from analysis.models import AnalysisObservation, AnalysisRequest, PromptCandidate, PromptProvenance
from analysis.providers import BrightDataProvider, OpenAIWebSearchExtractor, OxylabsProvider
from analysis.question_pipeline import OpenAIProcessor, cluster_questions, signals_to_questions
from analysis.reconstruction import PromptReconstructor, ReconstructionExample
from models.seed import Seed, SeedType, deduplicate_seeds
from scrapers import ForumScraper, ReviewScraper, SerpScraper, SocialScraper
from utils.config_loader import load_config


load_dotenv()


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
        response = requests.request(method, f"{self.url}/rest/v1/{table}{'?' + query if query else ''}", headers=headers, json=body, timeout=60)
        response.raise_for_status()
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
        self.worker_id = worker_id or os.getenv("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.cloud_execution_id = cloud_execution_id or os.getenv("CLOUD_RUN_EXECUTION") or os.getenv("CLOUD_RUN_TASK_ID") or "local"
        self.fanout_extractor = OpenAIWebSearchExtractor() if os.getenv("OPENAI_API_KEY") else None

    def _execute_analysis(self, provider, request: AnalysisRequest):
        observation = provider.execute(request)
        observation.metadata["response_source"] = observation.provider
        if not observation.fan_outs and self.fanout_extractor:
            extracted = self.fanout_extractor.extract(request)
            observation.fan_outs = extracted["queries"]
            observation.metadata.update({
                "fan_out_source": "openai_responses_web_search",
                "fan_out_model": extracted["model"],
                "fan_out_response_id": extracted["response_id"],
                "fan_out_search_calls": extracted["search_calls"],
                "fan_out_usage": extracted["usage"],
            })
        else:
            observation.metadata["fan_out_source"] = observation.provider
        return observation

    def _record_cost(self, job: Dict, provider: str, category: str, amount=None, quantity=None, unit=None, cost_status="actual", external_reference=None, metadata=None, dataset_id=None):
        reference = external_reference or f"{job['id']}:{provider}:{category}"
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

    def _persist_observation(self, prompt: Dict, observation):
        observation_rows = self.db.request("POST", "observations", body=[{"prompt_id": prompt["id"], "provider": observation.provider, "engine": observation.engine, "model": observation.model, "country": observation.country, "language": observation.language, "answer": observation.answer, "web_search_triggered": observation.web_search_triggered, "raw_response": observation.raw_response, "observed_at": observation.observed_at.isoformat()}])
        observation_id = observation_rows[0]["id"]
        if observation.fan_outs:
            self.db.request("POST", "fan_outs", body=[{"observation_id": observation_id, "position": index + 1, "query": query, "normalized_query": " ".join(query.casefold().split()), "source": observation.metadata.get("fan_out_source", observation.provider), "metadata": {"model": observation.metadata.get("fan_out_model"), "response_id": observation.metadata.get("fan_out_response_id")}} for index, query in enumerate(observation.fan_outs)])
        if observation.citations:
            self.db.request("POST", "citations", body=[{"observation_id": observation_id, "position": citation.position or index + 1, "url": citation.url, "title": citation.title, "excerpt": citation.text} for index, citation in enumerate(observation.citations)])
        return observation_id

    def _run_once(self, provider, candidate, example, engine, run_index, project, phase):
        return self._execute_analysis(provider, AnalysisRequest(
            prompt=candidate.text, engine=engine, country=project.get("country", "BE"),
            language=project.get("language", "fr"),
            metadata={"example_id": example["id"], "run_index": run_index, "phase": phase},
        ))

    def _stored_observations(self, prompt_id: str, engines=None):
        engine_filter = f"&engine=in.({','.join(engines)})" if engines else ""
        rows = self.db.request("GET", "observations", f"select=*&prompt_id=eq.{prompt_id}{engine_filter}&order=observed_at.asc")
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
            self._record_cost(job, "google_cloud", "cloud_run_job", quantity=runtime_seconds, unit="seconds", cost_status="pending_reconciliation", external_reference=f"{job['id']}:google_cloud:{self.cloud_execution_id}", metadata={"execution_id": self.cloud_execution_id, "cpu": 2, "memory_gib": 2})
            actual_cost, cost_status = self._job_cost_summary(job["id"])
            self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", {"status": "completed", "progress": 100, "output": result, "actual_cost_usd": actual_cost, "cost_status": cost_status, "heartbeat_at": datetime.now(timezone.utc).isoformat(), "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
        except Exception as error:
            runtime_seconds = round(time.monotonic() - started_monotonic, 3)
            try:
                self._record_cost(job, "google_cloud", "cloud_run_job", quantity=runtime_seconds, unit="seconds", cost_status="pending_reconciliation", external_reference=f"{job['id']}:google_cloud:{self.cloud_execution_id}", metadata={"execution_id": self.cloud_execution_id, "failed": True, "cpu": 2, "memory_gib": 2})
            except Exception:
                pass
            can_retry = int(job.get("attempt_count", 1)) < int(job.get("max_attempts", 3))
            self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", {"status": "pending" if can_retry else "failed", "error": str(error)[:2000], "heartbeat_at": datetime.now(timezone.utc).isoformat(), "completed_at": None if can_retry else datetime.now(timezone.utc).isoformat()}, "return=minimal")
            raise
        finally:
            heartbeat.stop()
        return True

    def _collect(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        config = load_config(self.config_path)
        input_config = job.get("input", {})
        budget = clamp_collection_budget(input_config.get("query_budget", 10))
        seed_ids = [str(seed_id) for seed_id in input_config.get("seed_ids", []) if seed_id]
        seed_filter = f"&id=in.({','.join(seed_ids)})" if seed_ids else ""

        def report(progress: int, stage: str, extra=None):
            self._report(job, progress, stage, extra)

        report(3, "Chargement des seeds")
        seed_rows = self.db.request("GET", "seeds", f"select=*&project_id=eq.{project_id}&enabled=eq.true{seed_filter}&order=priority.desc")
        report(8, f"{len(seed_rows)} seeds chargés · préparation des sources")
        config.scraping.serp["query_budget"] = budget
        config.scraping.forum["max_threads"] = budget
        config.scraping.reviews["max_pages"] = min(10, budget)
        config.seeds = deduplicate_seeds(Seed(
            value=row["value"], seed_type=SeedType(row["seed_type"]), priority=row["priority"],
            language=row["language"], market=row["market"], enabled=row["enabled"]
        ) for row in seed_rows)
        requested = set(job.get("input", {}).get("sources", []))
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

        forum_config = config.sources.get("forums", {})
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
        forum_config["platforms"] = platforms

        if "trustpilot_url" in source_config:
            trustpilot_url = str(source_config.get("trustpilot_url") or "").strip()
            config.sources.setdefault("reviews", {})["platforms"] = [{"name": "trustpilot", "url": trustpilot_url, "method": "api"}] if trustpilot_url else []
        if "serp_templates" in source_config:
            config.sources.setdefault("serp", {})["query_templates"] = clean_list("serp_templates")

        social_platforms = [platform for platform in ("reddit", "facebook", "instagram", "linkedin", "x") if platform in requested]
        if social_platforms:
            social_limits = {
                "targets": bounded_int("social_target_limit", min(budget, 20), 1, 50),
                "posts": bounded_int("social_post_limit", 10, 1, 50),
                "comments": bounded_int("social_comment_limit", 0, 0, 20),
            }
            config.sources["social"] = {
                "limits": social_limits,
                "reddit": {"subreddits": clean_list("subreddits"), "dataset_id": str(source_config.get("reddit_dataset_id") or "").strip()},
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
        for scraper in scrapers:
            scraper.progress_callback = lambda processed, total, detail, current=scraper: scraper_progress(current, processed, total, detail)
            before = len(items)
            items.extend(scraper.run())
            if isinstance(scraper, SocialScraper):
                for platform in scraper.platforms:
                    count = sum(1 for item in items[before:] if item.platform == platform)
                    source_report[platform] = {"collected": count, "errors": scraper.platform_errors.get(platform, 0)}
                    if scraper.skipped.get(platform):
                        source_report[platform]["skipped"] = scraper.skipped[platform]
            else:
                source_report[scraper.source_type] = {"collected": len(items) - before, "errors": scraper.errors_count}
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
        project = self.db.request("GET", "projects", f"select=language&id=eq.{project_id}&limit=1")[0]
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
        return {"questions": len(rows), "clusters": saved_count, "geo_relevant": sum(cluster["is_geo_relevant"] for cluster in clusters)}

    def _build_dataset(self, job: Dict) -> Dict:
        dataset_id = job["input"]["dataset_id"]
        dataset = self.db.request("GET", "datasets", f"select=*&id=eq.{dataset_id}&limit=1")[0]
        project_id = dataset["project_id"]
        cluster_rows = self.db.request("GET", "clusters", f"select=*&project_id=eq.{project_id}&is_geo_relevant=eq.true&order=question_count.desc")
        links = self.db.request("GET", "cluster_questions", "select=cluster_id,questions(text)")
        questions_by_cluster = {}
        cluster_ids = {row["id"] for row in cluster_rows}
        for link in links:
            if link["cluster_id"] in cluster_ids and link.get("questions"):
                questions_by_cluster.setdefault(link["cluster_id"], []).append(link["questions"]["text"])
        language = self.db.request("GET", "projects", f"select=language,country&id=eq.{project_id}&limit=1")[0]
        build_config = dataset.get("build_config", {})
        clusters = [ClusterInput(
            id=row["id"], label=row["label"], representative_question=row["representative_question"],
            questions=questions_by_cluster.get(row["id"], []), language=language.get("language", "fr"),
            question_count=row.get("question_count", 0), source_count=row.get("source_count", 0)
        ) for row in cluster_rows]
        candidates = score_candidates(DatasetBuilder().build(clusters, DatasetBuildConfig(
            personas=build_config.get("personas", []), stages=build_config.get("stages", ["discovery", "comparison"]),
            specificity_levels=build_config.get("specificity_levels", [0, 1, 2]),
            candidates_per_cluster=build_config.get("candidates_per_cluster", 9),
        ))[:dataset.get("candidate_pool_size", dataset["target_size"])])
        selected = stratified_sample(candidates, int(dataset.get("execution_sample_size", len(candidates))), int(build_config.get("max_per_cluster", 5)))
        selected_ids = {candidate.id for candidate in selected}
        repetitions = int(dataset["repetitions"])
        engines = dataset.get("engines", ["chatgpt"])
        cost = estimate_cost(len(selected), repetitions, len(engines), float(dataset.get("cost_per_execution_eur", 0)))
        if cost["estimated_cost_eur"] > float(dataset.get("max_budget_eur", 0)):
            raise RuntimeError(f"Estimated cost {cost['estimated_cost_eur']:.2f} EUR exceeds budget")
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
            "persona": candidate.metadata["persona"], "journey_stage": candidate.metadata["stage"],
            "specificity_level": candidate.metadata["specificity_level"],
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
        provider_name = os.getenv("DATASET_PROVIDER", "brightdata")
        provider = OxylabsProvider() if provider_name == "oxylabs" else BrightDataProvider()
        bright_cost_before = self._brightdata_account_cost() if provider_name == "brightdata" else None
        threshold = float(build_config.get("quality_threshold", 0.65))
        records = []
        accepted = rejected = completed = openai_search_calls = 0
        tasks = []
        stored_observations = {}
        for candidate in selected:
            prompt = prompts_by_text.get(candidate.text)
            example = examples_by_prompt.get(prompt["id"]) if prompt else None
            if not prompt or not example:
                continue
            existing = self._stored_observations(prompt["id"], engines)
            stored_observations[example["id"]] = existing
            if int(example.get("completed_runs") or 0) >= repetitions or min(sum(item.engine == engine for item in existing) for engine in engines) >= repetitions:
                accepted += int(example.get("status") == "accepted")
                rejected += int(example.get("status") == "rejected")
                continue
            records.append((candidate, prompt, example, existing))
            for engine in engines:
                completed_runs = sum(item.engine == engine for item in existing)
                for run_index in range(completed_runs, repetitions):
                    tasks.append((candidate, prompt, example, engine, run_index))
        openai_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        all_prompts = [candidate.text for candidate in candidates]
        total = max(1, len(tasks))
        expected = {example["id"]: repetitions * len(engines) for _, _, example, _ in records}
        received = {example["id"]: 0 for _, _, example, _ in records}
        concurrency = max(1, min(10, int(os.getenv("ANALYSIS_CONCURRENCY", "5"))))
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(self._run_once, provider, candidate, example, engine, run_index, language, "build"): (candidate, prompt, example) for candidate, prompt, example, engine, run_index in tasks}
            for future in as_completed(futures):
                candidate, prompt, example = futures[future]
                observation = future.result()
                self._persist_observation(prompt, observation)
                stored_observations[example["id"]].append(observation)
                received[example["id"]] += 1
                usage = observation.metadata.get("fan_out_usage") or {}
                openai_search_calls += int(observation.metadata.get("fan_out_search_calls") or 0)
                for key in openai_usage:
                    openai_usage[key] += int(usage.get(key) or 0)
                completed += 1
                if len(stored_observations[example["id"]]) == expected[example["id"]]:
                    scores = score_dataset_example(candidate, stored_observations[example["id"]], all_prompts)
                    is_accepted = scores["quality_score"] >= threshold
                    accepted += int(is_accepted)
                    rejected += int(not is_accepted)
                    self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {"status": "accepted" if is_accepted else "rejected", **scores, "completed_runs": repetitions, "rejection_reason": None if is_accepted else "quality_below_threshold"}, "return=minimal")
                    self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}", {"status": "validated" if is_accepted else "archived", "confidence": scores["quality_score"]}, "return=minimal")
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": min(95, 10 + int(85 * completed / total))}, "return=minimal")
        if openai_search_calls:
            self._record_cost(job, "openai", "web_search", quantity=openai_search_calls, unit="calls", cost_status="usage_only", metadata=openai_usage, dataset_id=dataset_id)
        bright_delta = None
        if provider_name == "brightdata":
            bright_cost_after = self._brightdata_account_cost()
            if bright_cost_before is not None and bright_cost_after is not None and bright_cost_after > bright_cost_before:
                bright_delta = round(bright_cost_after - bright_cost_before, 6)
                self._record_cost(job, "brightdata", "web_scraper_api", amount=bright_delta, quantity=completed, unit="records", cost_status="account_delta", metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
            else:
                self._record_cost(job, "brightdata", "web_scraper_api", quantity=completed, unit="records", cost_status="pending_reconciliation", metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
        statistics = {"candidates": len(candidates), "sampled": len(selected), "accepted": accepted, "rejected": rejected, "executions": completed, "concurrency": concurrency, "estimated_cost_eur": cost["estimated_cost_eur"], "confirmed_brightdata_cost_usd": bright_delta, "acceptance_rate": round(accepted / len(selected), 4) if selected else 0}
        confirmed_cost = bright_delta or 0
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "ready", "statistics": statistics, "actual_cost_usd": confirmed_cost, "cost_status": "partial" if openai_search_calls else "reconciled", "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
        return statistics

    def _validate_dataset(self, job: Dict) -> Dict:
        dataset_id = job["input"]["dataset_id"]
        target_runs = int(job["input"].get("target_runs", 3))
        limit = int(job["input"].get("limit", 100))
        dataset = self.db.request("GET", "datasets", f"select=*&id=eq.{dataset_id}&limit=1")[0]
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
            candidate = PromptCandidate(text=prompt["text"], provenance=PromptProvenance(prompt["provenance"]), source_reference=prompt.get("cluster_id") or "", expected_fan_outs=prompt.get("expected_fan_outs", []), metadata=prompt.get("metadata", {}))
            existing = self._stored_observations(prompt["id"], engines)
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
        provider = OxylabsProvider() if provider_name == "oxylabs" else BrightDataProvider()
        bright_cost_before = self._brightdata_account_cost() if provider_name == "brightdata" else None
        completed = openai_search_calls = 0
        openai_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        concurrency = max(1, min(10, int(os.getenv("ANALYSIS_CONCURRENCY", "5"))))
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(self._run_once, provider, candidate, example, engine, run_index, project, "validation"): (candidate, prompt, example) for candidate, prompt, example, engine, run_index in tasks}
            for future in as_completed(futures):
                candidate, prompt, example = futures[future]
                observation = future.result()
                self._persist_observation(prompt, observation)
                stored_observations[example["id"]].append(observation)
                usage = observation.metadata.get("fan_out_usage") or {}
                openai_search_calls += int(observation.metadata.get("fan_out_search_calls") or 0)
                for key in openai_usage:
                    openai_usage[key] += int(usage.get(key) or 0)
                completed += 1
                if min(sum(item.engine == engine for item in stored_observations[example["id"]]) for engine in engines) >= target_runs:
                    scores = score_dataset_example(candidate, stored_observations[example["id"]])
                    self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {**scores, "target_runs": target_runs, "completed_runs": target_runs, "validation_tier": 1 if target_runs == 5 else 2}, "return=minimal")
                self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": min(95, 10 + int(85 * completed / max(1, additional_executions)))}, "return=minimal")
        if openai_search_calls:
            self._record_cost(job, "openai", "web_search", quantity=openai_search_calls, unit="calls", cost_status="usage_only", metadata=openai_usage, dataset_id=dataset_id)
        bright_delta = None
        if provider_name == "brightdata":
            bright_cost_after = self._brightdata_account_cost()
            if bright_cost_before is not None and bright_cost_after is not None and bright_cost_after > bright_cost_before:
                bright_delta = round(bright_cost_after - bright_cost_before, 6)
                self._record_cost(job, "brightdata", "web_scraper_api", amount=bright_delta, quantity=completed, unit="records", cost_status="account_delta", metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
            else:
                self._record_cost(job, "brightdata", "web_scraper_api", quantity=completed, unit="records", cost_status="pending_reconciliation", metadata={"account_cost_before": bright_cost_before, "account_cost_after": bright_cost_after}, dataset_id=dataset_id)
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
        observations = self.db.request("GET", "observations", f"select=id,prompt_id&prompt_id=in.({','.join(prompts_by_id)})")
        observation_prompt = {row["id"]: row["prompt_id"] for row in observations}
        fan_out_rows = self.db.request("GET", "fan_outs", f"select=observation_id,query&observation_id=in.({','.join(observation_prompt)})") if observations else []
        fan_outs_by_prompt = {}
        for row in fan_out_rows:
            prompt_id = observation_prompt.get(row["observation_id"])
            if prompt_id:
                fan_outs_by_prompt.setdefault(prompt_id, []).append(row["query"])
        examples = [ReconstructionExample(prompts_by_id[prompt_id]["text"], fan_outs, prompt_id) for prompt_id, fan_outs in fan_outs_by_prompt.items() if fan_outs]
        if not examples:
            return {"examples": 0, "reconstructed": 0}
        reconstructor = PromptReconstructor(examples)
        clusters = self.db.request("GET", "clusters", f"select=*&project_id=eq.{project_id}&is_geo_relevant=eq.true")
        links = self.db.request("GET", "cluster_questions", "select=cluster_id,questions(text)")
        questions_by_cluster = {}
        for link in links:
            if link.get("questions"):
                questions_by_cluster.setdefault(link["cluster_id"], []).append(link["questions"]["text"])
        project = self.db.request("GET", "projects", f"select=language&id=eq.{project_id}&limit=1")[0]
        max_per_cluster = int(job.get("input", {}).get("max_candidates_per_cluster", 3))
        candidates = []
        for cluster in clusters:
            target = [cluster["representative_question"], *questions_by_cluster.get(cluster["id"], [])]
            for candidate in reconstructor.reconstruct(target, project.get("language", "fr"), max_per_cluster):
                candidate.source_reference = cluster["id"]
                candidate.metadata.update({"target_cluster_id": cluster["id"], "training_examples": len(examples)})
                candidates.append(candidate)
        rows = [{
            "project_id": project_id, "cluster_id": candidate.source_reference, "text": candidate.text,
            "provenance": "reverse_engineered", "confidence": candidate.confidence, "status": "draft",
            "expected_fan_outs": candidate.expected_fan_outs, "metadata": candidate.metadata,
        } for candidate in candidates]
        saved = self.db.request("POST", "prompts", "on_conflict=project_id,text", rows, "resolution=ignore-duplicates,return=representation") if rows else []
        return {"examples": len(examples), "clusters": len(clusters), "candidates": len(rows), "reconstructed": len(saved or [])}


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
