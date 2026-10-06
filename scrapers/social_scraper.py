import os
import re
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
        "x": "BRIGHTDATA_X_DATASET_ID",
    }
    comments_dataset_env = {
        "facebook": "BRIGHTDATA_FACEBOOK_COMMENTS_DATASET_ID",
        "instagram": "BRIGHTDATA_INSTAGRAM_COMMENTS_DATASET_ID",
    }

    def __init__(self, config: Config, platforms: List[str]):
        super().__init__(config)
        self.platforms = platforms
        self.api_key = os.getenv("BRIGHTDATA_API_KEY", "")
        self.timeout = int(os.getenv("BRIGHTDATA_SOCIAL_TIMEOUT", "240"))
        self.batch_size = int(os.getenv("BRIGHTDATA_SOCIAL_BATCH_SIZE", "20"))
        limits = self.config.sources.get("social", {}).get("limits", {})
        self.target_limit = int(limits.get("targets") or os.getenv("BRIGHTDATA_SOCIAL_TARGET_LIMIT", "20"))
        self.post_limit = int(limits.get("posts") or os.getenv("BRIGHTDATA_SOCIAL_POST_LIMIT", "10"))
        self.comment_limit = int(limits.get("comments") if limits.get("comments") is not None else os.getenv("BRIGHTDATA_SOCIAL_COMMENT_LIMIT", "5"))
        self.comment_target_limit = int(limits.get("comment_targets") or os.getenv("BRIGHTDATA_SOCIAL_COMMENT_TARGET_LIMIT", "5"))
        self.api_cost_usd = 0.0
        self.skipped: Dict[str, str] = {}
        self.platform_errors: Dict[str, int] = {platform: 0 for platform in platforms}
        self._progress_processed = 0
        self._progress_total = 1
        self._progress_label = "social"

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
            targets = self._valid_targets(platform, self._targets(platform))[:self.target_limit]
            if not dataset_id:
                self.skipped[platform] = f"{self.dataset_env[platform]} manquant"
                self.logger.warning(f"Bright Data dataset ID missing for {platform}")
                continue
            if not targets:
                self.skipped[platform] = "aucune cible configurée"
                continue
            for start in range(0, len(targets), self.batch_size):
                batch = targets[start:start + self.batch_size]
                label = batch[0].get("label") or batch[0].get("url") or batch[0].get("query")
                self._progress_processed = start
                self._progress_total = len(targets)
                self._progress_label = f"{platform} · {label}"
                self._report_progress(start, len(targets), f"{platform} · batch {start // self.batch_size + 1} · {len(batch)} cible(s)")
                try:
                    payload = [item for target in batch for item in self._payload(platform, target)]
                    request_params = self._discovery_params(platform, batch)
                    records = self._collect_dataset(dataset_id, payload, request_params, wrap_input=bool(request_params))
                    records = self._expand_records(platform, records)[:len(batch) * self.post_limit]
                    parsed = [self._record_to_item(platform, record, self._record_target(record, batch)) for record in records]
                    parsed.extend(self._collect_comment_items(platform, records, batch))
                    items.extend(item for item in parsed if item)
                    processed = min(start + len(batch), len(targets))
                    self._progress_processed = processed
                    self._report_progress(processed, len(targets), f"{platform} · {len(parsed)} signaux · batch {start // self.batch_size + 1}")
                except Exception as error:
                    self.errors_count += 1
                    self.platform_errors[platform] += 1
                    self.skipped[platform] = str(error)[:500]
                    self.logger.error(f"Bright Data {platform} error for batch starting at {label}: {error}")
                    processed = min(start + len(batch), len(targets))
                    self._progress_processed = processed
                    self._report_progress(processed, len(targets), f"{platform} · erreur sur le batch {start // self.batch_size + 1}")
            self._report_progress(platform_index, len(self.platforms), f"{platform} · {len(items)} signaux au total")
        self.items_scraped = len(items)
        return items

    def _normalize_social_url(self, platform: str, url: str) -> str:
        if platform == "instagram":
            match = re.search(r"instagram\.com/([a-zA-Z0-9._-]+)/?", url)
            if match:
                return f"https://www.instagram.com/{match.group(1)}/"
        if platform == "x":
            match = re.search(r"(?:twitter|x)\.com/([a-zA-Z0-9_]+)(?:/status/\d+)?", url)
            if match:
                return f"https://x.com/{match.group(1)}"
        return url

    def _targets(self, platform: str) -> List[Dict[str, str]]:
        social = self.config.sources.get("social", {})
        configured = social.get(platform, {})
        urls = configured.get("urls", [])
        if platform == "reddit" and not urls:
            subreddits = configured.get("subreddits", [])
            budget = int(self.config.scraping.forum.get("max_threads", 10))
            seeds = [seed.value for seed in self.config.seeds if seed.enabled][:budget]
            return [{"url": f"https://www.reddit.com/r/{subreddit}/search/?q={seed}&restrict_sr=1", "label": f"r/{subreddit} · {seed}", "query": seed, "subreddit": subreddit} for subreddit in subreddits for seed in seeds]
        seen = set()
        targets = []
        for url in urls:
            normalized = self._normalize_social_url(platform, url)
            if normalized in seen:
                continue
            seen.add(normalized)
            targets.append({"url": normalized, "label": normalized})
        return targets

    def _valid_targets(self, platform: str, targets: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if platform != "facebook":
            return targets
        valid = [target for target in targets if self._is_commentable_url("facebook", target.get("url", ""))]
        rejected = len(targets) - len(valid)
        if rejected:
            self.skipped[platform] = f"{rejected} URL(s) de page refusée(s) pour protéger le budget; fournissez des URLs de posts/reels précis"
        return valid

    def _payload(self, platform: str, target: Dict[str, str]) -> List[Dict[str, Any]]:
        if platform == "reddit" and target.get("query"):
            return [{"keyword": target["query"], "date": "Past month", "num_of_posts": self.post_limit}]
        payload: Dict[str, Any] = {"url": target["url"]}
        if platform == "instagram":
            payload["num_of_posts"] = self.post_limit
        return [payload]

    @staticmethod
    def _discovery_params(platform: str, targets: List[Dict[str, str]]) -> Dict[str, str]:
        if platform == "reddit":
            return {"type": "discover_new", "discover_by": "keyword"}
        if platform == "instagram":
            return {"type": "discover_new", "discover_by": "url"}
        if platform == "linkedin":
            discover_by = "company_url" if any("/company/" in target.get("url", "") for target in targets) else "profile_url"
            return {"type": "discover_new", "discover_by": discover_by}
        if platform == "x" and any("/status/" not in target.get("url", "") for target in targets):
            return {"type": "discover_new", "discover_by": "profile_url"}
        return {}

    def _post_with_retry(self, url: str, params: Dict[str, str], body: Any, max_retries: int = 2) -> requests.Response:
        response = None
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(url, params=params, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=body, timeout=min(120, self.timeout))
                if response.status_code not in {502, 503, 504}:
                    return response
                self.logger.warning(f"Bright Data transient HTTP {response.status_code}, retry {attempt + 1}/{max_retries}")
            except requests.Timeout:
                self.logger.warning(f"Bright Data timeout, retry {attempt + 1}/{max_retries}")
            if attempt < max_retries:
                time.sleep(5 * (attempt + 1))
        return response

    def _collect_dataset(self, dataset_id: str, payload: List[Dict[str, Any]], extra_params: Optional[Dict[str, str]] = None, wrap_input: bool = False) -> List[Dict[str, Any]]:
        params = {"dataset_id": dataset_id, "format": "json", "include_errors": "true", **(extra_params or {})}
        body: Any = {"input": payload, "limit_per_input": self.post_limit} if wrap_input else payload
        response = self._post_with_retry(self.endpoint, params, body)
        if not response or not response.ok:
            text = response.text[:500] if response else "no response"
            raise RuntimeError(f"Bright Data HTTP {getattr(response, 'status_code', 'unknown')}: {text}")
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

    def _expand_records(self, platform: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if platform != "instagram":
            return records
        expanded = []
        for record in records:
            posts = record.get("posts")
            if not isinstance(posts, list):
                expanded.append(record)
                continue
            for post in posts[:self.post_limit]:
                if not isinstance(post, dict):
                    continue
                item = dict(post)
                item.setdefault("user_posted", record.get("account") or record.get("user_name"))
                item.setdefault("url", post.get("url") or post.get("post_url"))
                expanded.append(item)
        return expanded

    def _wait_snapshot(self, snapshot_id: str) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = requests.get(f"https://api.brightdata.com/datasets/v3/progress/{snapshot_id}", headers=headers, timeout=30)
            response.raise_for_status()
            status = response.json().get("status")
            self._report_progress(self._progress_processed, self._progress_total, f"{self._progress_label} · Bright Data {status or 'en cours'}")
            if status == "ready":
                result = requests.get(f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}", params={"format": "json"}, headers=headers, timeout=120)
                result.raise_for_status()
                raw = result.json()
                return [record for record in raw if isinstance(record, dict)] if isinstance(raw, list) else []
            if status in {"failed", "canceled"}:
                raise RuntimeError(f"Bright Data snapshot {snapshot_id} ended with status {status}")
            time.sleep(5)
        raise RuntimeError(f"Bright Data snapshot {snapshot_id} timed out after {self.timeout}s")

    def _collect_comment_items(self, platform: str, records: List[Dict[str, Any]], targets: List[Dict[str, str]]) -> List[RawItem]:
        env_name = self.comments_dataset_env.get(platform)
        dataset_id = os.getenv(env_name, "") if env_name else ""
        if not dataset_id or self.comment_limit <= 0:
            return []
        post_urls = []
        for index, record in enumerate(records):
            url = str(record.get("post_url") or record.get("url") or targets[min(index, len(targets) - 1)].get("url") or "")
            if url and self._is_commentable_url(platform, url) and url not in post_urls:
                post_urls.append(url)
            if len(post_urls) >= self.comment_target_limit:
                break
        if not post_urls:
            return []
        self._progress_label = f"{platform} · commentaires"
        self._report_progress(self._progress_processed, self._progress_total, f"{platform} · commentaires sur {len(post_urls)} post(s)")
        try:
            comments = self._collect_dataset(dataset_id, [{"url": url} for url in post_urls])
        except Exception as error:
            self.errors_count += 1
            self.platform_errors[platform] += 1
            self.skipped[platform] = f"commentaires: {str(error)[:400]}"
            self.logger.error(f"Bright Data {platform} comments error: {error}")
            return []
        return [item for item in (self._comment_to_item(platform, record, post_urls[0]) for record in comments[:len(post_urls) * self.comment_limit]) if item]

    @staticmethod
    def _is_commentable_url(platform: str, url: str) -> bool:
        if platform == "instagram":
            return "/p/" in url or "/reel/" in url
        if platform == "facebook":
            return "/posts/" in url or "/reel/" in url or "story.php" in url or "story_fbid" in url
        return True

    def _comment_to_item(self, platform: str, record: Dict[str, Any], post_url: str) -> Optional[RawItem]:
        text = str(record.get("comment_text") or record.get("text") or record.get("comment") or record.get("content") or record.get("message") or "")
        if len(text.strip()) < 10:
            return None
        post_url = str(record.get("post_url") or record.get("source_url") or post_url)
        url = str(record.get("comment_url") or record.get("url") or post_url)
        return RawItem(
            source_type=SourceType.SOCIAL,
            platform=platform,
            raw_text=text.strip(),
            url=url,
            title="Commentaire",
            brand=self._detect_brand(text) or self.config.client.name,
            theme=self._detect_theme(text),
            metadata={"provider": "brightdata", "signal_kind": "comment", "post_url": post_url, "raw_record_keys": sorted(record.keys())[:30]},
            client_slug=self.config.client.slug,
        )

    def _record_target(self, record: Dict[str, Any], targets: List[Dict[str, str]]) -> Dict[str, str]:
        input_value = record.get("input")
        record_url = str(
            record.get("input_url")
            or (input_value.get("url") if isinstance(input_value, dict) else "")
            or record.get("url")
            or ""
        )
        for target in targets:
            if target.get("url") and target["url"] == record_url:
                return target
        return targets[0]

    def _record_to_item(self, platform: str, record: Dict[str, Any], target: Dict[str, str]) -> Optional[RawItem]:
        comments = record.get("comments") or record.get("top_comments") or []
        comment_texts = []
        if isinstance(comments, list):
            for comment in comments[:self.comment_limit]:
                if isinstance(comment, dict):
                    value = comment.get("text") or comment.get("comment") or comment.get("content") or ""
                    if value:
                        comment_texts.append(str(value))
        title = str(record.get("title") or record.get("headline") or record.get("post_title") or "")
        body = str(record.get("text") or record.get("content") or record.get("post_text") or record.get("description") or record.get("caption") or "")
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
            metadata={"provider": "brightdata", "target": target, "comment_count": len(comment_texts), "limits": {"posts": self.post_limit, "comments": self.comment_limit}, "raw_record_keys": sorted(record.keys())[:30]},
            client_slug=self.config.client.slug,
        )
