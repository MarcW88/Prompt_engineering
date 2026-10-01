from typing import Dict, List, Optional
import requests

from analysis.models import AnalysisRequest
from .base import MissingCredentialsError, ProviderError


class OpenAIWebSearchExtractor:
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-5.4-mini", timeout: int = 180):
        import os
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_WEB_SEARCH_MODEL", model)
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def extract(self, request: AnalysisRequest) -> Dict:
        if not self.api_key:
            raise MissingCredentialsError("OpenAI requires OPENAI_API_KEY for web-search fan-outs")
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "input": request.prompt,
                "tools": [{"type": "web_search"}],
                "tool_choice": "required",
            },
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderError(f"OpenAI web search returned HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        queries = []
        seen = set()
        search_calls = 0
        for item in data.get("output", []):
            if item.get("type") != "web_search_call":
                continue
            search_calls += 1
            action = item.get("action") or {}
            values = action.get("queries") or ([action.get("query")] if action.get("query") else [])
            for value in values:
                text = str(value).strip()
                key = text.casefold()
                if text and key not in seen:
                    seen.add(key)
                    queries.append(text)
        return {
            "queries": queries,
            "model": data.get("model", self.model),
            "response_id": data.get("id"),
            "search_calls": search_calls,
            "usage": data.get("usage", {}),
        }
