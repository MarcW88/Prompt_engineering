#!/usr/bin/env python3
import argparse
import hashlib
import os
from datetime import datetime, timezone
from typing import Dict

import requests
from dotenv import load_dotenv

from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder
from analysis.dataset_quality import score_dataset_example
from analysis.models import AnalysisRequest
from analysis.providers import BrightDataProvider, OxylabsProvider
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


class CollectionWorker:
    def __init__(self, config_path: str):
        self.db = SupabaseRest()
        self.config_path = config_path

    def run_once(self) -> bool:
        jobs = self.db.request("GET", "jobs", "select=*&kind=in.(collect_sources,transform_signals,cluster_questions,build_dataset,reverse_engineer)&status=eq.pending&order=created_at.asc&limit=1")
        if not jobs:
            return False
        job = jobs[0]
        self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"status": "running", "progress": 5}, "return=minimal")
        try:
            handlers = {
                "collect_sources": self._collect,
                "transform_signals": self._transform_signals,
                "cluster_questions": self._cluster_questions,
                "build_dataset": self._build_dataset,
                "reverse_engineer": self._reverse_engineer,
            }
            result = handlers[job["kind"]](job)
            self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"status": "completed", "progress": 100, "output": result, "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
        except Exception as error:
            self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"status": "failed", "error": str(error), "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
            raise
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
            questions=questions_by_cluster.get(row["id"], []), language=language.get("language", "fr")
        ) for row in cluster_rows]
        candidates = DatasetBuilder().build(clusters, DatasetBuildConfig(
            personas=build_config.get("personas", []), stages=build_config.get("stages", ["discovery", "comparison"]),
            specificity_levels=build_config.get("specificity_levels", [0, 1, 2]),
            candidates_per_cluster=build_config.get("candidates_per_cluster", 9),
        ))[:dataset["target_size"]]
        prompt_rows = self.db.request("POST", "prompts", body=[{
            "project_id": project_id, "cluster_id": candidate.source_reference, "text": candidate.text,
            "provenance": candidate.provenance.value, "confidence": candidate.confidence, "status": "testing",
            "expected_fan_outs": candidate.expected_fan_outs, "metadata": candidate.metadata,
        } for candidate in candidates]) if candidates else []
        examples = self.db.request("POST", "dataset_examples", body=[{
            "dataset_id": dataset_id, "prompt_id": prompt["id"], "cluster_id": prompt["cluster_id"],
            "status": "executing", "persona": candidate.metadata["persona"],
            "journey_stage": candidate.metadata["stage"], "specificity_level": candidate.metadata["specificity_level"],
            "expected_sub_intents": candidate.expected_fan_outs,
        } for prompt, candidate in zip(prompt_rows, candidates)]) if prompt_rows else []
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "executing"}, "return=minimal")
        provider_name = os.getenv("DATASET_PROVIDER", "brightdata")
        provider = OxylabsProvider() if provider_name == "oxylabs" else BrightDataProvider()
        repetitions = int(dataset["repetitions"])
        engines = dataset.get("engines", ["chatgpt"])
        threshold = float(build_config.get("quality_threshold", 0.65))
        accepted = 0
        rejected = 0
        all_prompts = [candidate.text for candidate in candidates]
        total = max(1, len(candidates) * repetitions * len(engines))
        completed = 0
        for candidate, prompt, example in zip(candidates, prompt_rows, examples):
            observations = []
            for engine in engines:
                for _ in range(repetitions):
                    observation = provider.execute(AnalysisRequest(
                        prompt=candidate.text, engine=engine, country=language.get("country", "BE"),
                        language=language.get("language", "fr"), metadata={"dataset_id": dataset_id, "example_id": example["id"]}
                    ))
                    observations.append(observation)
                    observation_rows = self.db.request("POST", "observations", body=[{
                        "prompt_id": prompt["id"], "provider": observation.provider, "engine": observation.engine,
                        "model": observation.model, "country": observation.country, "language": observation.language,
                        "answer": observation.answer, "web_search_triggered": observation.web_search_triggered,
                        "raw_response": observation.raw_response, "observed_at": observation.observed_at.isoformat(),
                    }])
                    observation_id = observation_rows[0]["id"]
                    if observation.fan_outs:
                        self.db.request("POST", "fan_outs", body=[{
                            "observation_id": observation_id, "position": index + 1, "query": query,
                            "normalized_query": " ".join(query.casefold().split()),
                        } for index, query in enumerate(observation.fan_outs)])
                    if observation.citations:
                        self.db.request("POST", "citations", body=[{
                            "observation_id": observation_id, "position": citation.position or index + 1,
                            "url": citation.url, "title": citation.title, "excerpt": citation.text,
                        } for index, citation in enumerate(observation.citations)])
                    completed += 1
                    progress = min(95, 10 + int(85 * completed / total))
                    self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"progress": progress}, "return=minimal")
            scores = score_dataset_example(candidate, observations, all_prompts)
            is_accepted = scores["quality_score"] >= threshold
            accepted += int(is_accepted)
            rejected += int(not is_accepted)
            self.db.request("PATCH", "dataset_examples", f"id=eq.{example['id']}", {
                "status": "accepted" if is_accepted else "rejected", **scores,
                "rejection_reason": None if is_accepted else "quality_below_threshold",
            }, "return=minimal")
            self.db.request("PATCH", "prompts", f"id=eq.{prompt['id']}", {
                "status": "validated" if is_accepted else "archived", "confidence": scores["quality_score"],
            }, "return=minimal")
        statistics = {"candidates": len(candidates), "accepted": accepted, "rejected": rejected, "executions": completed, "acceptance_rate": round(accepted / len(candidates), 4) if candidates else 0}
        self.db.request("PATCH", "datasets", f"id=eq.{dataset_id}", {"status": "ready", "statistics": statistics, "completed_at": datetime.now(timezone.utc).isoformat()}, "return=minimal")
        return statistics

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
    args = parser.parse_args()
    worker = CollectionWorker(args.config)
    if args.once:
        worker.run_once()
        return
    while worker.run_once():
        pass


if __name__ == "__main__":
    main()
