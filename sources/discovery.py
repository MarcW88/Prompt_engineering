"""Découverte d'URLs sources (forums, articles, discussions).

Cascade :
1. SearXNG self-hosté (variable d'env SEARXNG_URL) -> gratuit.
2. DataForSEO organic live -> fallback payant fiable.

Retourne une liste de {"url", "title", "snippet"} prête à être extraite
par scrapers.extractors.
"""

import base64
import os
import time
from typing import Any, Dict, List, Optional

import requests


class SourceDiscovery:
    def __init__(self, searxng_url: str = "", delay: float = 1.0,
                 timeout: int = 30, logger=None,
                 dataforseo_login: str = "", dataforseo_password: str = ""):
        self.searxng_url = (searxng_url or os.getenv("SEARXNG_URL", "")).rstrip("/")
        self.delay = delay
        self.timeout = timeout
        self.logger = logger
        login = dataforseo_login or os.getenv("DATAFORSEO_LOGIN", "")
        password = dataforseo_password or os.getenv("DATAFORSEO_PASSWORD", "")
        self.dataforseo_auth = None
        if login and password:
            auth = base64.b64encode(f"{login}:{password}".encode()).decode()
            self.dataforseo_auth = f"Basic {auth}"
        self.api_cost_usd = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PromptFinder/1.0 (source discovery)",
            "Accept": "application/json",
        })
        self.searxng_available: Optional[bool] = None

    def search(self, query: str, limit: int = 10,
               language: str = "fr", country: str = "FR") -> List[Dict[str, Any]]:
        """Retourne des URLs candidates pour une requête."""
        if self.searxng_url:
            results = self._searxng_search(query, limit, language)
            if results:
                return results
        return self._dataforseo_search(query, limit, language, country)

    def _searxng_search(self, query: str, limit: int, language: str) -> List[Dict[str, Any]]:
        try:
            time.sleep(self.delay)
            response = self.session.get(
                f"{self.searxng_url}/search",
                params={"q": query, "format": "json", "language": language},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                self.searxng_available = False
                if self.logger:
                    self.logger.warning(f"SearXNG HTTP {response.status_code}; fallback DataForSEO")
                return []
            results = response.json().get("results") or []
            self.searxng_available = True
            return [{
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": item.get("content", ""),
                "engine": item.get("engine", "searxng"),
            } for item in results[:limit] if item.get("url")]
        except Exception as error:
            self.searxng_available = False
            if self.logger:
                self.logger.warning(f"SearXNG unavailable ({error}); fallback DataForSEO")
            return []

    def _dataforseo_search(self, query: str, limit: int,
                           language: str, country: str) -> List[Dict[str, Any]]:
        if not self.dataforseo_auth:
            if self.logger:
                self.logger.warning("No SearXNG nor DataForSEO credentials for discovery")
            return []
        location_codes = {"FR": 2250, "BE": 2064, "CH": 2756, "LU": 2442, "CA": 2124}
        try:
            time.sleep(self.delay)
            response = requests.post(
                "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
                headers={"Authorization": self.dataforseo_auth, "Content-Type": "application/json"},
                json=[{
                    "keyword": query,
                    "location_code": location_codes.get(country.upper(), 2250),
                    "language_code": language,
                    "device": "desktop",
                    "os": "windows",
                    "depth": min(limit, 100),
                }],
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            self.api_cost_usd += float(result.get("cost") or 0)
            if result.get("status_code") != 20000:
                return []
            tasks = result.get("tasks") or []
            task_result = (tasks[0].get("result") or []) if tasks else []
            if not task_result or not isinstance(task_result[0], dict):
                return []
            items = task_result[0].get("items") or []
            return [{
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": item.get("description", ""),
                "engine": "dataforseo",
            } for item in items[:limit] if item.get("type") == "organic" and item.get("url")]
        except Exception as error:
            if self.logger:
                self.logger.error(f"DataForSEO discovery error: {error}")
            return []
