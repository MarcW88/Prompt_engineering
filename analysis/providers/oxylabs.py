from typing import Any, Dict, Optional
import requests

from analysis.models import AnalysisObservation, AnalysisRequest
from .base import AnalysisProvider, MissingCredentialsError, ProviderError, first_value, normalize_citations, normalize_fan_outs


class OxylabsProvider(AnalysisProvider):
    name = "oxylabs"
    endpoint = "https://realtime.oxylabs.io/v1/queries"

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None, timeout: int = 120):
        self.username = username or self.env("OXYLABS_USERNAME")
        self.password = password or self.env("OXYLABS_PASSWORD")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password)

    def execute(self, request: AnalysisRequest) -> AnalysisObservation:
        if not self.is_configured:
            raise MissingCredentialsError("Oxylabs requires OXYLABS_USERNAME and OXYLABS_PASSWORD")
        payload = {
            "source": self._source(request.engine),
            "query": request.prompt,
            "geo_location": request.country,
            "locale": request.language,
            "parse": True,
        }
        response = requests.post(
            self.endpoint,
            auth=(self.username, self.password),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderError(f"Oxylabs returned HTTP {response.status_code}: {response.text[:300]}")
        return self.parse_response(request, response.json())

    def parse_response(self, request: AnalysisRequest, raw: Any) -> AnalysisObservation:
        if not isinstance(raw, dict):
            raise ProviderError("Oxylabs returned an unsupported response")
        results = raw.get("results") or []
        record = results[0] if isinstance(results, list) and results else raw
        content = record.get("content", record) if isinstance(record, dict) else {}
        if isinstance(content, str):
            answer, parsed = content, {}
        else:
            parsed = content if isinstance(content, dict) else {}
            answer = first_value(parsed, ["answer", "response", "content", "text"])
        fan_outs = first_value(parsed, ["query_fan_out", "query_fan_outs", "search_queries", "queries"], [])
        citations = first_value(parsed, ["citations", "sources", "links", "references"], [])
        return AnalysisObservation(
            prompt=request.prompt,
            provider=self.name,
            engine=request.engine,
            answer=str(answer or ""),
            fan_outs=normalize_fan_outs(fan_outs),
            citations=normalize_citations(citations),
            country=request.country,
            language=request.language,
            model=str(first_value(parsed, ["model", "model_name", "version"])),
            web_search_triggered=parsed.get("web_search_triggered"),
            raw_response=raw,
            metadata=request.metadata,
        )

    @staticmethod
    def _source(engine: str) -> str:
        sources: Dict[str, str] = {
            "chatgpt": "chatgpt",
            "perplexity": "perplexity",
            "google_ai_mode": "google_ai_mode",
            "google": "google_search",
        }
        if engine not in sources:
            raise ProviderError(f"Oxylabs engine not supported: {engine}")
        return sources[engine]
