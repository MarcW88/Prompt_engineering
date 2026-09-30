from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List
import os

from analysis.models import AnalysisObservation, AnalysisRequest, Citation


class ProviderError(RuntimeError):
    pass


class MissingCredentialsError(ProviderError):
    pass


class AnalysisProvider(ABC):
    name = "base"

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    def execute(self, request: AnalysisRequest) -> AnalysisObservation:
        pass

    def execute_many(self, requests: Iterable[AnalysisRequest]) -> List[AnalysisObservation]:
        return [self.execute(request) for request in requests]

    @staticmethod
    def env(name: str) -> str:
        return os.getenv(name, "").strip()


def first_value(data: Dict[str, Any], keys: List[str], default: Any = "") -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return default


def normalize_citations(values: Any) -> List[Citation]:
    if not isinstance(values, list):
        return []
    citations = []
    for index, value in enumerate(values, 1):
        if isinstance(value, str):
            citations.append(Citation(url=value, position=index))
        elif isinstance(value, dict):
            url = first_value(value, ["url", "link", "href", "source_url"])
            if url:
                citations.append(Citation(
                    url=url,
                    title=first_value(value, ["title", "name"]),
                    text=first_value(value, ["text", "snippet", "description"]),
                    position=value.get("position", value.get("rank", index))
                ))
    return citations


def normalize_fan_outs(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for value in values:
        if isinstance(value, dict):
            value = first_value(value, ["query", "text", "title", "keyword"])
        text = str(value).strip() if value else ""
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
