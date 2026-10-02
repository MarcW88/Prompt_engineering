import os
import time
from typing import Any, Dict, List, Optional

import requests

from .base_scraper import BaseScraper
from models.raw_item import RawItem, SourceType
from utils.config_loader import Config


class SocialScraper(BaseScraper):
    """Collecte les posts/commentaires publics via les datasets Bright Data."""

    endpoint = "https://api.brightdata.com/datasets/v3/scrape"

    dataset_env = {
        "reddit": "BRIGHTDATA_REDDIT_DATASET_ID",
        "facebook": "BRIGHTDATA_FACEBOOK_DATASET_ID",
        "instagram": "BRIGHTDATA_INSTAGRAM_DATASET_ID",
        "linkedin": "BRIGHTDATA_LINKEDIN_DATASET_ID",
    }

    def __init__(self, config: Config, platforms: List[str]):
        super().__init__(config)
        self.platforms = platforms
        self.api_key = os.getenv("BRIGHTDATA_API_KEY", "")
        self.timeout = int(os.getenv("BRIGHTDATA_SOCIAL_TIMEOUT", "900"))
        self.api_cost_usd = 0.0
        self.skipped: Dict[str, str] = {}

    @property
    def source_type(self) -> str:
        return "social"

    @property
    def is_enabled(self) -> bool:
        return bool(self.platforms)

    def run(self) -> List[RawItem]:
        if not self.api_key:
            self.skipped = {platform: "BRIGHTDATA_API_KEY manquant" for platform in self.platforms}
            self.logger.warning("Bright Data API key missing; social collection skipped")
            return []

        items: List[RawItem] = []
        for platform_index, platform in enumerate(self.platforms, start=1):
            configured = self.config.sources.get("social", {}).get(platform, {})
            dataset_id = configured.get("dataset_id") or os.getenv(self.dataset_env[platform], "")
            targets = self._targets(platform)
            if not dataset_id:
                self.skipped[platform] = f"{self.dataset_env[platform]} manquant"
                self.logger.warning(f"Bright Data dataset ID missing for {platform}")
                continue
            if not targets:
                self.skipped[platform] = "aucune cible configurée"
                continue
            for index, target in enumerate(targets, start=1):
                label = target.get("label") or target.get("url") or target.get("query")
                self._report_progress(index - 1, len(targets), f"{platform} · {label}")
                try:
                    records = self._collect_dataset(dataset_id, self._payload(platform, target))
                    parsed = [self._record_to_item(platform, record, target) for record in records]
                    items.extend(item for item in parsed if item)
                    self._report_progress(index, len(targets), f"{platform} · {label} · {len(parsed)} signaux")
                except Exception as error:
                    self.errors_count += 1
                    self.skipped[platform] = str(error)[:200]
                    self.logger.error(f"Bright Data {platform} error for {label}: {error}")
                    self._report_progress(index, len(targets), f"{platform} · erreur sur {label}")
            self._report_progress(platform_index, len(self.platforms), f"{platform} · {len(items)} signaux au total")
        self.items_scraped = len(items)
        return items

    def _targets(self, platform: str) -> List[Dict[str, str]]:
        social = self.config.sources.get("social", {})
        configured = social.get(platform, {})
        urls = configured.get("urls", [])
        if platform == "reddit" and not urls:
            subreddits = configured.get("subreddits", [])
            budget = int(self.config.scraping.forum.get("max_threads", 10))
            seeds = [seed.value for seed in self.config.seeds if seed.enabled][:budget]
            return [{"url": f"https://www.reddit.com/r/{subreddit}/search/?q={seed}&restrict_sr=1", "label": f"r/{subreddit} · {seed}", "query": seed, "subreddit": subreddit} for subreddit in subreddits for seed in seeds]
        return [{"url": url, "label": url} for url in urls]

    def _payload(self, platform: str, target: Dict[str, str]) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"url": target["url"]}
        if target.get("query"):
            payload["query"] = target["query"]
        if platform == "reddit" and target.get("subreddit"):
            payload["subreddit"] = target["subreddit"]
        return [payload]

    def _collect_dataset(self, dataset_id: str, payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        response = requests.post(
            self.endpoint,
            params={"dataset_id": dataset_id, "format": "json", "include_errors": "true"},
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=min(120, self.timeout),
        )
        response.raise_for_status()
        raw = response.json()
        if response.status_code == 202 or isinstance(raw, dict) and raw.get("snapshot_id"):
            snapshot_id = raw.get("snapshot_id") if isinstance(raw, dict) else None
            if not snapshot_id:
                raise RuntimeError("Bright Data pending response without snapshot_id")
            return self._wait_snapshot(snapshot_id)
        if isinstance(raw, list):
            return [record for record in raw if isinstance(record, dict)]
        if isinstance(raw, dict):
            for key in ("results", "items", "data", "posts"):
                if isinstance(raw.get(key), list):
                    return [record for record in raw[key] if isinstance(record, dict)]
            return [raw]
        return []

    def _wait_snapshot(self, snapshot_id: str) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = requests.get(f"https://api.brightdata.com/datasets/v3/progress/{snapshot_id}", headers=headers, timeout=30)
            response.raise_for_status()
            status = response.json().get("status")
            if status == "ready":
                result = requests.get(f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}", params={"format": "json"}, headers=headers, timeout=120)
                result.raise_for_status()
                raw = result.json()
                return [record for record in raw if isinstance(record, dict)] if isinstance(raw, list) else []
            if status in {"failed", "canceled"}:
                raise RuntimeError(f"Bright Data snapshot {snapshot_id} ended with status {status}")
            time.sleep(5)
        raise RuntimeError(f"Bright Data snapshot {snapshot_id} timed out")

    def _record_to_item(self, platform: str, record: Dict[str, Any], target: Dict[str, str]) -> Optional[RawItem]:
        comments = record.get("comments") or record.get("top_comments") or []
        comment_texts = []
        if isinstance(comments, list):
            for comment in comments[:10]:
                if isinstance(comment, dict):
                    value = comment.get("text") or comment.get("comment") or comment.get("content") or ""
                    if value:
                        comment_texts.append(str(value))
        title = str(record.get("title") or record.get("headline") or record.get("post_title") or "")
        body = str(record.get("text") or record.get("content") or record.get("post_text") or record.get("description") or "")
        raw_text = "\n\n".join(part for part in [title, body, *comment_texts] if part).strip()
        if len(raw_text) < 20:
            return None
        url = str(record.get("url") or record.get("post_url") or record.get("link") or target.get("url") or "")
        return RawItem(
            source_type=SourceType.SOCIAL,
            platform=platform,
            raw_text=raw_text,
            url=url,
            title=title or None,
            brand=self._detect_brand(raw_text) or self.config.client.name,
            theme=self._detect_theme(raw_text),
            metadata={"provider": "brightdata", "target": target, "comment_count": len(comment_texts), "raw_record_keys": sorted(record.keys())[:30]},
            client_slug=self.config.client.slug,
        )
