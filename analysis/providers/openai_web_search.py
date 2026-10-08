from typing import Dict, List, Optional
import os
import requests

from analysis.models import AnalysisObservation, AnalysisRequest, Citation
from .base import AnalysisProvider, MissingCredentialsError, ProviderError, normalize_fan_outs


class OpenAILLMProvider(AnalysisProvider):
    """Fast direct OpenAI execution for prompt reverse-engineering.

    This is much faster than Bright Data snapshots but only returns web-search
    fan-outs via the OpenAI responses API. It is meant for full audits where
    speed matters more than real rendered-page observations.
    """
    name = "openai"

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini", timeout: int = 60):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_LLM_MODEL", model)
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def execute(self, request: AnalysisRequest) -> AnalysisObservation:
        if not self.api_key:
            raise MissingCredentialsError("OpenAI requires OPENAI_API_KEY")
        if os.getenv("OPENAI_LLM_WEB_SEARCH", "1") != "0":
            return self._execute_with_web_search(request)
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Answer the user's question."},
            {"role": "user", "content": request.prompt},
        ]
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": 0.7},
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderError(f"OpenAI returned HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        choice = data.get("choices", [{}])[0]
        answer = str(choice.get("message", {}).get("content", ""))
        # Extract search-like fan-outs from the answer heuristically.
        fan_outs = self._extract_fan_outs(answer)
        citations = []
        for index, url in enumerate(normalize_fan_outs(data.get("citations", []))):
            citations.append(Citation(url=url, position=index + 1))
        return AnalysisObservation(
            prompt=request.prompt,
            provider=self.name,
            engine=request.engine,
            answer=answer,
            fan_outs=fan_outs,
            citations=citations,
            country=request.country,
            language=request.language,
            model=data.get("model", self.model),
            raw_response=data,
            metadata=request.metadata,
        )

    def _execute_with_web_search(self, request: AnalysisRequest) -> AnalysisObservation:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_WEB_SEARCH_MODEL", "gpt-5.4-mini"),
                "input": request.prompt,
                "tools": [{"type": "web_search"}],
            },
            timeout=max(self.timeout, 180),
        )
        if not response.ok:
            raise ProviderError(f"OpenAI web search returned HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        fan_outs = []
        seen = set()
        citations = []
        answer = ""
        for item in data.get("output", []):
            if item.get("type") == "web_search_call":
                action = item.get("action") or {}
                for value in action.get("queries") or ([action.get("query")] if action.get("query") else []):
                    text = str(value).strip()
                    if text and text.casefold() not in seen:
                        seen.add(text.casefold())
                        fan_outs.append(text)
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        answer += content.get("text", "")
                        for annotation in content.get("annotations", []):
                            if annotation.get("type") == "url_citation":
                                citations.append(Citation(url=annotation.get("url", ""), position=len(citations) + 1))
        return AnalysisObservation(
            prompt=request.prompt,
            provider=self.name,
            engine=request.engine,
            answer=answer,
            fan_outs=fan_outs,
            citations=citations,
            country=request.country,
            language=request.language,
            model=data.get("model", self.model),
            web_search_triggered=bool(fan_outs),
            raw_response=data,
            metadata=request.metadata,
        )

    @staticmethod
    def _extract_fan_outs(answer: str) -> List[str]:
        # Simple heuristic: bullet lines containing a question or query intent.
        results = []
        for line in answer.split("\n"):
            stripped = line.strip().lstrip("-•*1234567890. ").strip()
            if stripped and (stripped.endswith("?") or any(stripped.lower().startswith(w) for w in ["how", "what", "why", "where", "when", "qui", "que", "quoi", "comment", "où", "quand", "pourquoi"])):
                results.append(stripped)
        return results[:10]


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
