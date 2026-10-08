from typing import Any, Dict, Optional
import requests

from analysis.models import AnalysisObservation, AnalysisRequest
from .base import AnalysisProvider, MissingCredentialsError, ProviderError, first_value, normalize_citations, normalize_fan_outs


class DataForSEOProvider(AnalysisProvider):
    """Realtime LLM executions via DataForSEO AI Optimization API.

    Pay-per-task (no subscription) and supports real ChatGPT, Gemini and
    Perplexity responses with optional web_search grounding.
    """

    name = "dataforseo"
    base_url = "https://api.dataforseo.com/v3"
    engine_paths = {
        "chatgpt": "ai_optimization/chat_gpt",
        "gemini": "ai_optimization/gemini",
        "perplexity": "ai_optimization/perplexity",
        "claude": "ai_optimization/claude",
    }
    default_models = {
        "chatgpt": "gpt-4.1-mini",
        "gemini": "gemini-2.5-flash",
        "perplexity": "sonar",
        "claude": "claude-3-5-sonnet",
    }
    geo_supported = {"chatgpt", "perplexity", "claude"}
    country_locations = {"BE": "Belgium", "FR": "France", "NL": "Netherlands", "DE": "Germany", "US": "United States", "GB": "United Kingdom"}

    def __init__(self, login: Optional[str] = None, password: Optional[str] = None, timeout: int = 120):
        self.login = login or self.env("DATAFORSEO_LOGIN")
        self.password = password or self.env("DATAFORSEO_PASSWORD")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.login and self.password)

    def execute(self, request: AnalysisRequest) -> AnalysisObservation:
        if not self.is_configured:
            raise MissingCredentialsError("DataForSEO requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD")
        if request.engine == "google_ai_mode":
            return self._execute_google_ai_mode(request)
        path = self.engine_paths.get(request.engine)
        if not path:
            raise ProviderError(f"DataForSEO ne supporte pas le moteur {request.engine}")
        task = {
            # DataForSEO limits user_prompt to 500 characters.
            "user_prompt": request.prompt[:500],
            "model_name": self.env(f"DATAFORSEO_{request.engine.upper()}_MODEL") or self.default_models[request.engine],
            "web_search": True,
        }
        if request.country and request.engine in self.geo_supported:
            task["web_search_country_iso_code"] = request.country.upper()[:2]
        if request.language and request.engine in self.geo_supported:
            task["web_search_language_iso_code"] = request.language.lower()[:2]
        if request.engine == "gemini":
            task["max_output_tokens"] = 1024
        response = requests.post(
            f"{self.base_url}/{path}/llm_responses/live",
            auth=(self.login, self.password),
            headers={"Content-Type": "application/json"},
            json=[task],
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderError(f"DataForSEO returned HTTP {response.status_code}: {response.text[:300]}")
        return self.parse_response(request, response.json())

    def _execute_google_ai_mode(self, request: AnalysisRequest) -> AnalysisObservation:
        location = self.country_locations.get(request.country.upper()[:2], request.country)
        task = {
            # AI Mode keyword is limited to 700 characters.
            "keyword": request.prompt[:700],
            "location_name": location,
            "language_code": "en",
            "device": "desktop",
            "os": "windows",
        }
        response = requests.post(
            f"{self.base_url}/serp/google/ai_mode/live/advanced",
            auth=(self.login, self.password),
            headers={"Content-Type": "application/json"},
            json=[task],
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderError(f"DataForSEO AI Mode returned HTTP {response.status_code}: {response.text[:300]}")
        return self._parse_ai_mode(request, response.json())

    def _parse_ai_mode(self, request: AnalysisRequest, raw: Any) -> AnalysisObservation:
        tasks = raw.get("tasks") or []
        task = tasks[0] if tasks else {}
        status = task.get("status_code")
        if status and status >= 40000:
            raise ProviderError(f"DataForSEO AI Mode task failed: {task.get('status_message')}")
        results = task.get("result") or []
        record = results[0] if isinstance(results, list) and results else {}
        overview = next((item for item in record.get("items") or [] if isinstance(item, dict) and item.get("type") == "ai_overview"), {})
        elements = overview.get("items") or []
        answer = "".join(str(el.get("markdown") or el.get("text") or "") for el in elements if isinstance(el, dict))
        references = overview.get("references") or []
        citations = [{"url": ref.get("url", ""), "title": ref.get("title", ""), "text": ref.get("text", "")} for ref in references if isinstance(ref, dict)]
        return AnalysisObservation(
            prompt=request.prompt,
            provider=self.name,
            engine=request.engine,
            answer=answer,
            fan_outs=[],
            citations=normalize_citations(citations),
            country=request.country,
            language=request.language,
            model="google-ai-mode",
            web_search_triggered=bool(overview),
            raw_response=record or raw,
            metadata=request.metadata,
        )

    def parse_response(self, request: AnalysisRequest, raw: Any) -> AnalysisObservation:
        if not isinstance(raw, dict):
            raise ProviderError("DataForSEO returned an unsupported response")
        tasks = raw.get("tasks") or []
        task = tasks[0] if tasks else {}
        status = task.get("status_code")
        if status and status >= 40000:
            raise ProviderError(f"DataForSEO task failed: {task.get('status_message')}")
        results = task.get("result") or []
        record = results[0] if isinstance(results, list) and results else {}
        items = record.get("items") or [record]
        item = items[0] if isinstance(items, list) and items else {}
        sections = item.get("sections") if isinstance(item.get("sections"), list) else []
        answer = "".join(str(section.get("text", "")) for section in sections if isinstance(section, dict))
        if not answer:
            answer = str(first_value(item, ["answer", "response_text", "text", "markdown", "content"]) or first_value(record, ["answer", "response_text", "text", "markdown", "content"]) or "")
        annotations = []
        for section in sections:
            if isinstance(section, dict):
                annotations.extend(section.get("annotations") or [])
        fan_outs = first_value(item, ["fan_out_queries", "search_queries", "queries"]) or first_value(record, ["fan_out_queries", "search_queries", "queries"], [])
        citations = annotations or first_value(item, ["citations", "sources", "references", "links"]) or first_value(record, ["citations", "sources", "references", "links"], [])
        return AnalysisObservation(
            prompt=request.prompt,
            provider=self.name,
            engine=request.engine,
            answer=str(answer or ""),
            fan_outs=normalize_fan_outs(fan_outs),
            citations=normalize_citations(citations),
            country=request.country,
            language=request.language,
            model=str(first_value(record, ["model_name", "model", "version"], task.get("model_name", ""))),
            web_search_triggered=bool(task.get("web_search")),
            raw_response=record or raw,
            metadata=request.metadata,
        )
