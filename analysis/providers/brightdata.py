from typing import Any, Dict, Iterable, List, Optional
import time
import requests

from analysis.models import AnalysisObservation, AnalysisRequest
from .base import AnalysisProvider, MissingCredentialsError, ProviderError, first_value, normalize_citations, normalize_fan_outs


class BrightDataProvider(AnalysisProvider):
    name = "brightdata"
    endpoint = "https://api.brightdata.com/datasets/v3/scrape"

    def __init__(self, api_key: Optional[str] = None, dataset_ids: Optional[Dict[str, str]] = None, timeout: int = 900, batch_size: int = 10):
        self.api_key = api_key or self.env("BRIGHTDATA_API_KEY")
        self.dataset_ids = dataset_ids or {
            "chatgpt": self.env("BRIGHTDATA_CHATGPT_DATASET_ID"),
            "perplexity": self.env("BRIGHTDATA_PERPLEXITY_DATASET_ID"),
            "gemini": self.env("BRIGHTDATA_GEMINI_DATASET_ID"),
            "google_ai_mode": self.env("BRIGHTDATA_GOOGLE_AI_MODE_DATASET_ID"),
        }
        self.timeout = timeout
        self.batch_size = max(1, min(50, batch_size))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and any(self.dataset_ids.values()))

    def execute_many(self, requests: Iterable[AnalysisRequest]) -> List[AnalysisObservation]:
        # Bright Data supports batched snapshots: send many inputs in one call.
        # This is much faster than one snapshot per request.
        items = list(requests)
        if not items:
            return []
        observations = []
        for index in range(0, len(items), self.batch_size):
            batch = items[index:index + self.batch_size]
            observations.extend(self._execute_batch(batch))
        return observations

    def _execute_batch(self, analysis_requests: List[AnalysisRequest]) -> List[AnalysisObservation]:
        if not analysis_requests:
            return []
        first = analysis_requests[0]
        dataset_id = self.dataset_ids.get(first.engine, "")
        if not self.api_key or not dataset_id:
            raise MissingCredentialsError(
                f"Bright Data requires BRIGHTDATA_API_KEY and a dataset ID for {first.engine}"
            )
        payload = [{
            "url": self._engine_url(first.engine),
            "prompt": request.prompt,
            "country": request.country.upper(),
            "web_search": request.web_search,
            "additional_prompt": self._language_instruction(request.language),
        } for request in analysis_requests]
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
        snapshot_id = None
        if response.status_code == 202 or isinstance(raw, dict) and raw.get("snapshot_id"):
            snapshot_id = raw.get("snapshot_id")
            if not snapshot_id:
                raise ProviderError("Bright Data returned a pending response without snapshot_id")
            raw = self._wait_for_snapshot(snapshot_id)
        if isinstance(raw, dict):
            records = raw.get("data", [raw])
        elif isinstance(raw, list):
            records = raw
        else:
            records = []
        results = []
        for request, record in zip(analysis_requests, records):
            observation = self.parse_response(request, record)
            if snapshot_id:
                observation.metadata["brightdata_snapshot_id"] = snapshot_id
            results.append(observation)
        return results

    def execute(self, request: AnalysisRequest) -> AnalysisObservation:
        return self._execute_batch([request])[0]

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
        if not fan_outs:
            # ChatGPT exposes its real search queries under
            # metadata.search_model_queries (and variants), nested in the record.
            fan_outs = self._deep_search_queries(record)
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

    @classmethod
    def _deep_search_queries(cls, node: Any, depth: int = 0) -> List[str]:
        """Cherche récursivement les requêtes de recherche du moteur dans la
        réponse, notamment metadata.search_model_queries.queries (format ChatGPT
        observé dans les conversations et dans les datasets Bright Data)."""
        if depth > 8 or node is None:
            return []
        if isinstance(node, dict):
            for key in ("search_model_queries", "search_queries", "web_search_queries"):
                if key in node:
                    value = node[key]
                    if isinstance(value, dict):
                        queries = value.get("queries")
                        if isinstance(queries, list):
                            flattened = []
                            for query in queries:
                                if isinstance(query, dict):
                                    flattened.append(str(query.get("q") or query.get("query") or query.get("search_query") or ""))
                                else:
                                    flattened.append(str(query))
                            flattened = [query for query in flattened if query]
                            if flattened:
                                return flattened
                    if isinstance(value, list):
                        flattened = [
                            str(item.get("q") or item.get("query") or item.get("search_query") or item)
                            for item in value
                        ]
                        flattened = [query for query in flattened if query]
                        if flattened:
                            return flattened
            for value in node.values():
                found = cls._deep_search_queries(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = cls._deep_search_queries(item, depth + 1)
                if found:
                    return found
        return []

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
