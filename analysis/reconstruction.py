from dataclasses import dataclass
from typing import Iterable, List, Optional

from analysis.models import AnalysisObservation, PromptCandidate, PromptProvenance
from analysis.signatures import build_signature, signature_similarity


@dataclass
class ReconstructionExample:
    prompt: str
    fan_outs: List[str]
    source_reference: str = ""


class PromptReconstructor:
    def __init__(self, examples: Optional[Iterable[ReconstructionExample]] = None):
        self.examples = list(examples or [])

    @classmethod
    def from_observations(cls, observations: Iterable[AnalysisObservation]):
        return cls(ReconstructionExample(
            prompt=observation.prompt,
            fan_outs=observation.fan_outs,
            source_reference=observation.id,
        ) for observation in observations if observation.fan_outs)

    def reconstruct(self, fan_outs: List[str], language: str = "fr", max_candidates: int = 3) -> List[PromptCandidate]:
        target = build_signature(fan_outs)
        ranked = []
        for example in self.examples:
            score = signature_similarity(target, build_signature(example.fan_outs))
            ranked.append((score, example))
        ranked.sort(key=lambda item: item[0], reverse=True)
        candidates = [PromptCandidate(
            text=example.prompt,
            provenance=PromptProvenance.REVERSE_ENGINEERED,
            source_reference=example.source_reference,
            confidence=round(score, 4),
            expected_fan_outs=target.queries,
            metadata={"method": "nearest_fan_out_signature", "language": language},
        ) for score, example in ranked[:max_candidates] if score > 0]
        if not candidates and target.queries:
            candidates.append(PromptCandidate(
                text=self._fallback_prompt(target.queries, language),
                provenance=PromptProvenance.REVERSE_ENGINEERED,
                confidence=0.2,
                expected_fan_outs=target.queries,
                metadata={"method": "deterministic_fallback", "language": language},
            ))
        return candidates

    @staticmethod
    def _fallback_prompt(fan_outs: List[str], language: str) -> str:
        joined = ", ".join(fan_outs[:4])
        templates = {
            "fr": "Peux-tu m'aider à choisir en tenant compte de ces critères : {criteria} ?",
            "nl": "Kun je me helpen kiezen op basis van deze criteria: {criteria}?",
            "en": "Can you help me choose based on these criteria: {criteria}?",
        }
        return templates.get(language, templates["en"]).format(criteria=joined)
