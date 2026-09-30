from dataclasses import dataclass, field
from itertools import product
from typing import Dict, Iterable, List, Sequence

from analysis.models import PromptCandidate, PromptProvenance


DEFAULT_PERSONAS = {
    "fr": ["débutant", "utilisateur expérimenté", "acheteur attentif au budget"],
    "nl": ["beginner", "ervaren gebruiker", "prijsbewuste koper"],
    "en": ["beginner", "experienced user", "budget-conscious buyer"],
}
DEFAULT_STAGES = ["discovery", "comparison"]
DEFAULT_SPECIFICITY = [0, 1, 2]


@dataclass(frozen=True)
class ClusterInput:
    id: str
    label: str
    representative_question: str
    questions: Sequence[str] = field(default_factory=list)
    language: str = "fr"
    question_count: int = 0
    source_count: int = 0


@dataclass(frozen=True)
class DatasetBuildConfig:
    personas: Sequence[str] = field(default_factory=list)
    stages: Sequence[str] = field(default_factory=lambda: DEFAULT_STAGES)
    specificity_levels: Sequence[int] = field(default_factory=lambda: DEFAULT_SPECIFICITY)
    candidates_per_cluster: int = 9


class DatasetBuilder:
    def build(self, clusters: Iterable[ClusterInput], config: DatasetBuildConfig) -> List[PromptCandidate]:
        candidates = []
        for cluster in clusters:
            candidates.extend(self.build_cluster(cluster, config))
        return candidates

    def build_cluster(self, cluster: ClusterInput, config: DatasetBuildConfig) -> List[PromptCandidate]:
        personas = list(config.personas) or DEFAULT_PERSONAS.get(cluster.language, DEFAULT_PERSONAS["en"])
        combinations = product(personas, config.stages, config.specificity_levels)
        expected = self._expected_sub_intents(cluster)
        candidates = []
        seen = set()
        for persona, stage, specificity in combinations:
            prompt = self._render(cluster.representative_question, persona, stage, specificity, cluster.language, expected)
            normalized = " ".join(prompt.casefold().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(PromptCandidate(
                text=prompt,
                provenance=PromptProvenance.SYNTHETIC,
                source_reference=cluster.id,
                confidence=0.5,
                expected_fan_outs=expected,
                metadata={
                    "method": "controlled_matrix",
                    "cluster_id": cluster.id,
                    "cluster_label": cluster.label,
                    "persona": persona,
                    "stage": stage,
                    "specificity_level": specificity,
                    "language": cluster.language,
                    "cluster_question_count": cluster.question_count or len(cluster.questions) + 1,
                    "cluster_source_count": cluster.source_count,
                },
            ))
            if len(candidates) >= config.candidates_per_cluster:
                break
        return candidates

    @staticmethod
    def _expected_sub_intents(cluster: ClusterInput) -> List[str]:
        values = [cluster.representative_question, *cluster.questions]
        seen = set()
        result = []
        for value in values:
            normalized = " ".join(value.casefold().split())
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value.strip())
        return result[:8]

    @staticmethod
    def _render(question: str, persona: str, stage: str, specificity: int, language: str, sub_intents: Sequence[str]) -> str:
        context = ", ".join(sub_intents[1:4])
        if language == "fr":
            lead = f"Je suis {persona}. "
            action = "Aide-moi à comparer les options et à choisir" if stage == "comparison" else "Aide-moi à comprendre mes options"
            detail = ""
            if specificity == 1 and context:
                detail = f" Prends aussi en compte : {context}."
            elif specificity >= 2:
                detail = f" Donne des critères concrets, les compromis et une recommandation argumentée.{f' Prends aussi en compte : {context}.' if context else ''}"
            return f"{lead}{action} pour cette question : {question.rstrip('?')}.{detail}".strip()
        lead = f"I am a {persona}. "
        action = "Help me compare the options and decide" if stage == "comparison" else "Help me understand my options"
        detail = ""
        if specificity == 1 and context:
            detail = f" Also consider: {context}."
        elif specificity >= 2:
            detail = f" Give concrete criteria, trade-offs, and a reasoned recommendation.{f' Also consider: {context}.' if context else ''}"
        return f"{lead}{action} for this question: {question.rstrip('?')}.{detail}".strip()
