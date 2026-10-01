from typing import Any, Dict, Optional
import time
import requests

from analysis.models import AnalysisObservation, AnalysisRequest
from .base import AnalysisProvider, MissingCredentialsError, ProviderError, first_value, normalize_citations, normalize_fan_outs


class BrightDataProvider(AnalysisProvider):
    name = "brightdata"
    endpoint = "https://api.brightdata.com/datasets/v3/scrape"

    def __init__(self, api_key: Optional[str] = None, dataset_ids: Optional[Dict[str, str]] = None, timeout: int = 300):
        self.api_key = api_key or self.env("BRIGHTDATA_API_KEY")
        self.dataset_ids = dataset_ids or {
            "chatgpt": self.env("BRIGHTDATA_CHATGPT_DATASET_ID"),
            "perplexity": self.env("BRIGHTDATA_PERPLEXITY_DATASET_ID"),
            "gemini": self.env("BRIGHTDATA_GEMINI_DATASET_ID"),
            "google_ai_mode": self.env("BRIGHTDATA_GOOGLE_AI_MODE_DATASET_ID"),
        }
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and any(self.dataset_ids.values()))

    def execute(self, request: AnalysisRequest) -> AnalysisObservation:
        dataset_id = self.dataset_ids.get(request.engine, "")
        if not self.api_key or not dataset_id:
            raise MissingCredentialsError(
                f"Bright Data requires BRIGHTDATA_API_KEY and a dataset ID for {request.engine}"
            )
        payload = [{
            "url": self._engine_url(request.engine),
            "prompt": request.prompt,
            "country": request.country.upper(),
            "require_sources": True,
            "web_search": request.web_search,
            "additional_prompt": self._language_instruction(request.language),
        }]
        response = requests.post(
            self.endpoint,
            params={"dataset_id": dataset_id, "format": "json", "include_errors": "true"},
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderError(f"Bright Data returned HTTP {response.status_code}: {response.text[:300]}")
        raw = response.json()
        if response.status_code == 202 or isinstance(raw, dict) and raw.get("snapshot_id"):
            snapshot_id = raw.get("snapshot_id")
            if not snapshot_id:
                raise ProviderError("Bright Data returned a pending response without snapshot_id")
            raw = self._wait_for_snapshot(snapshot_id)
        return self.parse_response(request, raw)

    def _wait_for_snapshot(self, snapshot_id: str):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = requests.get(f"https://api.brightdata.com/datasets/v3/progress/{snapshot_id}", headers=headers, timeout=30)
            response.raise_for_status()
            status = response.json().get("status")
            if status == "ready":
                result = requests.get(f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}", params={"format": "json"}, headers=headers, timeout=60)
                result.raise_for_status()
                return result.json()
            if status in {"failed", "canceled"}:
                raise ProviderError(f"Bright Data snapshot {snapshot_id} ended with status {status}")
            time.sleep(5)
        raise ProviderError(f"Bright Data snapshot {snapshot_id} did not complete within {self.timeout}s")

    def parse_response(self, request: AnalysisRequest, raw: Any) -> AnalysisObservation:
        record = raw[0] if isinstance(raw, list) and raw else raw
        if not isinstance(record, dict):
            raise ProviderError("Bright Data returned an unsupported response")
        answer = first_value(record, ["answer_text_markdown", "answer_text", "answer", "response", "content", "text"])
        fan_outs = first_value(record, ["query_fan_out", "query_fan_outs", "web_search_query", "search_queries", "queries"], [])
        citations = first_value(record, ["citations", "search_sources", "references", "sources", "links"], [])
        return AnalysisObservation(
            prompt=request.prompt,
            provider=self.name,
            engine=request.engine,
            answer=str(answer or ""),
            fan_outs=normalize_fan_outs(fan_outs),
            citations=normalize_citations(citations),
            country=request.country,
            language=request.language,
            model=str(first_value(record, ["model", "model_name", "version"])),
            web_search_triggered=record.get("web_search_triggered"),
            raw_response=record,
            metadata=request.metadata,
        )

    @staticmethod
    def _language_instruction(language: str) -> str:
        return {
            "fr": "Réponds en français.",
            "nl": "Antwoord in het Nederlands.",
            "en": "Answer in English.",
        }.get(language, f"Answer in {language}.")

    @staticmethod
    def _engine_url(engine: str) -> str:
        return {
            "chatgpt": "https://chatgpt.com/",
            "perplexity": "https://www.perplexity.ai/",
            "gemini": "https://gemini.google.com/",
            "google_ai_mode": "https://www.google.com/",
        }.get(engine, "https://chatgpt.com/")
