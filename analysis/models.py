from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class PromptProvenance(str, Enum):
    OBSERVED = "observed"
    REVERSE_ENGINEERED = "reverse_engineered"
    SYNTHETIC = "synthetic"


@dataclass
class AnalysisRequest:
    prompt: str
    engine: str = "chatgpt"
    country: str = "FR"
    language: str = "fr"
    web_search: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Citation:
    url: str
    title: str = ""
    text: str = ""
    position: Optional[int] = None


@dataclass
class AnalysisObservation:
    prompt: str
    provider: str
    engine: str
    answer: str = ""
    fan_outs: List[str] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    country: str = "FR"
    language: str = "fr"
    model: str = ""
    web_search_triggered: Optional[bool] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PromptCandidate:
    text: str
    provenance: PromptProvenance
    source_reference: str = ""
    confidence: float = 0.0
    expected_fan_outs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
