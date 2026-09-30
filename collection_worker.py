#!/usr/bin/env python3
import argparse
import hashlib
import os
from datetime import datetime, timezone
from typing import Dict

import requests
from dotenv import load_dotenv

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
        jobs = self.db.request("GET", "jobs", "select=*&kind=eq.collect_sources&status=eq.pending&order=created_at.asc&limit=1")
        if not jobs:
            return False
        job = jobs[0]
        self.db.request("PATCH", "jobs", f"id=eq.{job['id']}", {"status": "running", "progress": 5}, "return=minimal")
        try:
            result = self._collect(job)
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
