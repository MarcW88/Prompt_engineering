#!/usr/bin/env python3
import argparse
import hashlib
import os
import socket
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict

import requests
from dotenv import load_dotenv

from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder
from analysis.dataset_quality import score_dataset_example
from analysis.dataset_funnel import estimate_cost, score_candidates, stratified_sample
from analysis.models import AnalysisRequest, PromptCandidate, PromptProvenance
from analysis.providers import BrightDataProvider, OpenAIWebSearchExtractor, OxylabsProvider
from analysis.question_pipeline import OpenAIProcessor, cluster_questions, signals_to_questions
from analysis.reconstruction import PromptReconstructor, ReconstructionExample
from models.seed import Seed, SeedType, deduplicate_seeds
from scrapers import ForumScraper, SerpScraper
from utils.config_loader import load_config


load_dotenv()


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
            })
        else:
            observation.metadata["fan_out_source"] = observation.provider
        return observation

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
            self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", {"status": "completed", "progress": 100, "output": result, "heartbeat_at": datetime.now(timezone.utc).isoformat(), "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
        except Exception as error:
            can_retry = int(job.get("attempt_count", 1)) < int(job.get("max_attempts", 3))
            self.db.request("PATCH", "jobs", f"id=eq.{job['id']}&worker_id=eq.{self.worker_id}&status=eq.running", {"status": "pending" if can_retry else "failed", "error": str(error)[:2000], "heartbeat_at": datetime.now(timezone.utc).isoformat(), "completed_at": None if can_retry else datetime.now(timezone.utc).isoformat()}, "return=minimal")
            raise
        finally:
            heartbeat.stop()
        return True

    def _collect(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        config = load_config(self.config_path)
        seed_rows = self.db.request("GET", "seeds", f"select=*&project_id=eq.{project_id}&enabled=eq.true&order=priority.desc")
        config.seeds = deduplicate_seeds(Seed(
            value=row["value"], seed_type=SeedType(row["seed_type"]), priority=row["priority"],
            language=row["language"], market=row["market"], enabled=row["enabled"]
        ) for row in seed_rows)
        requested = set(job.get("input", {}).get("sources", []))
        forum_config = config.sources.get("forums", {})
        platforms = forum_config.get("platforms", [])
        if "reddit" not in requested:
            platforms = [platform for platform in platforms if platform.get("name") != "reddit"]
        if "forum" not in requested:
            platforms = [platform for platform in platforms if platform.get("name") == "reddit"]
        forum_config["platforms"] = platforms
        scrapers = []
        if requested & {"reddit", "forum"}:
            scrapers.append(ForumScraper(config))
        if "serp" in requested:
            scrapers.append(SerpScraper(config))
        items = [item for scraper in scrapers for item in scraper.run()]
        rows = [{
            "project_id": project_id, "source_type": item.source_type.value, "platform": item.platform,
            "raw_text": item.raw_text, "title": item.title, "url": item.url, "theme": item.theme,
            "brand": item.brand, "metadata": item.metadata,
            "content_hash": hashlib.sha256(f"{item.platform}:{item.raw_text.casefold()}".encode()).hexdigest(),
        } for item in items]
        imported = 0
        for start in range(0, len(rows), 200):
            batch = rows[start:start + 200]
            saved = self.db.request("POST", "signals", "on_conflict=project_id,content_hash", batch, "resolution=ignore-duplicates,return=representation")
            imported += len(saved or [])
        return {"collected": len(rows), "imported": imported, "sources": sorted(requested), "seeds": len(config.seeds)}

    def _transform_signals(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        project = self.db.request("GET", "projects", f"select=language&id=eq.{project_id}&limit=1")[0]
        signals = self.db.request("GET", "signals", f"select=*&project_id=eq.{project_id}&order=collected_at.asc")
        existing = self.db.request("GET", "questions", f"select=signal_id&project_id=eq.{project_id}&signal_id=not.is.null")
        processed_ids = {row["signal_id"] for row in existing}
        pending = [signal for signal in signals if signal["id"] not in processed_ids]
        processor = None

        def transform(text, title, language):
            nonlocal processor
            processor = processor or OpenAIProcessor()
            return processor.transform(text, title, language)

        questions = signals_to_questions(pending, project.get("language", "fr"), transform)
        rows = [{
            "project_id": project_id, "signal_id": question.signal_id, "text": question.text,
            "provenance": question.provenance, "language": question.language,
            "confidence": question.confidence, "metadata": question.metadata,
        } for question in questions]
        saved = self.db.request("POST", "questions", "on_conflict=project_id,signal_id,text", rows, "resolution=ignore-duplicates,return=representation") if rows else []
        if job.get("input", {}).get("chain_cluster"):
            self.db.request("POST", "jobs", body=[{
                "project_id": project_id, "kind": "cluster_questions", "status": "pending",
                "depends_on": job["id"], "input": job["input"].get("cluster_config", {}),
            }])
        return {"signals": len(signals), "pending": len(pending), "questions": len(saved or [])}

    def _cluster_questions(self, job: Dict) -> Dict:
        project_id = job["project_id"]
        rows = self.db.request("GET", "questions", f"select=*&project_id=eq.{project_id}&order=created_at.asc")
        if not rows:
            return {"questions": 0, "clusters": 0}
        processor = OpenAIProcessor()
        embeddings = processor.embeddings([row["text"] for row in rows])
        input_config = job.get("input", {})
        clusters = cluster_questions(rows, embeddings, float(input_config.get("similarity_threshold", 0.82)), int(input_config.get("min_cluster_size", 2)))
        saved_count = 0
        for cluster in clusters:
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
        prompt_rows = self.db.request("POST", "prompts", body=[{
            "project_id": project_id, "cluster_id": candidate.source_reference, "text": candidate.text,
            "provenance": candidate.provenance.value, "confidence": candidate.confidence,
            "status": "testing" if candidate.id in selected_ids else "draft",
            "expected_fan_outs": candidate.expected_fan_outs, "metadata": candidate.metadata,
        } for candidate in candidates]) if candidates else []
        examples = self.db.request("POST", "dataset_examples", body=[{
            "dataset_id": dataset_id, "prompt_id": prompt["id"], "cluster_id": prompt["cluster_id"],
            "status": "executing" if candidate.id in selected_ids else "candidate",
            "persona": candidate.metadata["persona"], "journey_stage": candidate.metadata["stage"],
            "specificity_level": candidate.metadata["specificity_level"],
            "expected_sub_intents": candidate.expected_fan_outs,
            "pre_execution_score": candidate.confidence,
            "selected_for_execution": candidate.id in selected_ids,
            "selection_reason": "stratified_screening" if candidate.id in selected_ids else "candidate_pool",
            "validation_tier": 3, "target_runs": repetitions,
        } for prompt, candidate in zip(prompt_rows, candidates)]) if prompt_rows else []
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "executing", "estimated_cost_eur": cost["estimated_cost_eur"]}, "return=minimal")
        provider_name = os.getenv("DATASET_PROVIDER", "brightdata")
        provider = OxylabsProvider() if provider_name == "oxylabs" else BrightDataProvider()
        threshold = float(build_config.get("quality_threshold", 0.65))
        accepted = rejected = completed = 0
        all_prompts = [candidate.text for candidate in candidates]
        total = max(1, len(selected) * repetitions * len(engines))
        for candidate, prompt, example in zip(candidates, prompt_rows, examples):
            if candidate.id not in selected_ids:
                continue
            observations = []
            for engine in engines:
                for _ in range(repetitions):
                    observation = self._execute_analysis(provider, AnalysisRequest(prompt=candidate.text, engine=engine, country=language.get("country", "BE"), language=language.get("language", "fr"), metadata={"dataset_id": dataset_id, "example_id": example["id"]}))
                    observations.append(observation)
                    observation_rows = self.db.request("POST", "observations", body=[{"prompt_id": prompt["id"], "provider": observation.provider, "engine": observation.engine, "model": observation.model, "country": observation.country, "language": observation.language, "answer": observation.answer, "web_search_triggered": observation.web_search_triggered, "raw_response": observation.raw_response, "observed_at": observation.observed_at.isoformat()}])
                    observation_id = observation_rows[0]["id"]
                    if observation.fan_outs:
                        self.db.request("POST", "fan_outs", body=[{"observation_id": observation_id, "position": index + 1, "query": query, "normalized_query": " ".join(query.casefold().split()), "source": observation.metadata.get("fan_out_source", observation.provider), "metadata": {"model": observation.metadata.get("fan_out_model"), "response_id": observation.metadata.get("fan_out_response_id")}} for index, query in enumerate(observation.fan_outs)])
                    if observation.citations:
                        self.db.request("POST", "citations", body=[{"observation_id": observation_id, "position": citation.position or index + 1, "url": citation.url, "title": citation.title, "excerpt": citation.text} for index, citation in enumerate(observation.citations)])
                    completed += 1
                    self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": min(95, 10 + int(85 * completed / total))}, "return=minimal")
            scores = score_dataset_example(candidate, observations, all_prompts)
            is_accepted = scores["quality_score"] >= threshold
            accepted += int(is_accepted)
            rejected += int(not is_accepted)
            self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {"status": "accepted" if is_accepted else "rejected", **scores, "completed_runs": repetitions, "rejection_reason": None if is_accepted else "quality_below_threshold"}, "return=minimal")
            self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}", {"status": "validated" if is_accepted else "archived", "confidence": scores["quality_score"]}, "return=minimal")
        statistics = {"candidates": len(candidates), "sampled": len(selected), "accepted": accepted, "rejected": rejected, "executions": completed, "estimated_cost_eur": cost["estimated_cost_eur"], "acceptance_rate": round(accepted / len(selected), 4) if selected else 0}
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "ready", "statistics": statistics, "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
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
        additional_executions = sum(max(0, target_runs - int(example.get("completed_runs", 0))) * len(engines) for example in examples)
        additional_cost = additional_executions * float(dataset.get("cost_per_execution_eur", 0))
        projected_cost = float(dataset.get("estimated_cost_eur", 0)) + additional_cost
        if projected_cost > float(dataset.get("max_budget_eur", 0)):
            raise RuntimeError(f"Projected cost {projected_cost:.2f} EUR exceeds budget")
        provider = OxylabsProvider() if os.getenv("DATASET_PROVIDER", "brightdata") == "oxylabs" else BrightDataProvider()
        completed = 0
        for example in examples:
            prompt = prompts[example["prompt_id"]]
            candidate = PromptCandidate(text=prompt["text"], provenance=PromptProvenance(prompt["provenance"]), source_reference=prompt.get("cluster_id") or "", expected_fan_outs=prompt.get("expected_fan_outs", []), metadata=prompt.get("metadata", {}))
            observations = []
            remaining = max(0, target_runs - int(example.get("completed_runs", 0)))
            for engine in engines:
                for _ in range(remaining):
                    observation = self._execute_analysis(provider, AnalysisRequest(prompt=prompt["text"], engine=engine, country=project.get("country", "BE"), language=project.get("language", "fr"), metadata={"dataset_id": dataset_id, "example_id": example["id"], "validation_wave": target_runs}))
                    observations.append(observation)
                    observation_rows = self.db.request("POST", "observations", body=[{"prompt_id": prompt["id"], "provider": observation.provider, "engine": observation.engine, "model": observation.model, "country": observation.country, "language": observation.language, "answer": observation.answer, "web_search_triggered": observation.web_search_triggered, "raw_response": observation.raw_response, "observed_at": observation.observed_at.isoformat()}])
                    observation_id = observation_rows[0]["id"]
                    if observation.fan_outs:
                        self.db.request("POST", "fan_outs", body=[{"observation_id": observation_id, "position": index + 1, "query": query, "normalized_query": " ".join(query.casefold().split()), "source": observation.metadata.get("fan_out_source", observation.provider), "metadata": {"model": observation.metadata.get("fan_out_model"), "response_id": observation.metadata.get("fan_out_response_id")}} for index, query in enumerate(observation.fan_outs)])
                    completed += 1
            scores = score_dataset_example(candidate, observations) if observations else {}
            self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {**scores, "target_runs": target_runs, "completed_runs": target_runs, "validation_tier": 1 if target_runs == 5 else 2}, "return=minimal")
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"estimated_cost_eur": round(projected_cost, 2)}, "return=minimal")
        return {"selected": len(examples), "executions": completed, "target_runs": target_runs, "additional_cost_eur": round(additional_cost, 2)}

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
