from dataclasses import dataclass, field
from itertools import product
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Union

from analysis.models import PromptCandidate, PromptProvenance
from analysis.signatures import build_signature, signature_similarity


DEFAULT_PERSONAS = {
    "fr": ["débutant", "utilisateur expérimenté", "acheteur attentif au budget"],
    "nl": ["beginner", "ervaren gebruiker", "prijsbewuste koper"],
    "en": ["beginner", "experienced user", "budget-conscious buyer"],
}
DEFAULT_STAGES = ["discovery", "comparison"]
DEFAULT_SPECIFICITY = [0, 1, 2]

# Tokens that change the expected answer: a different budget, audience or usage
# must never be merged into the same intent, nor added without a source.
_CONSTRAINT_TERMS = {
    "débutant", "débutante", "beginner", "novice", "expert", "expérimenté", "experienced",
    "enfant", "enfants", "child", "children", "kids", "adulte", "adult", "senior",
    "femme", "homme", "women", "men", "pro", "professionnel", "professional",
    "budget", "pas cher", "cheap", "premium", "gratuit", "free",
}


@dataclass(frozen=True)
class QuestionItem:
    text: str
    provenance: str = "observed"  # observed | transformed


@dataclass(frozen=True)
class ClusterInput:
    id: str
    label: str
    representative_question: str
    questions: Sequence[Union[str, QuestionItem, Mapping]] = field(default_factory=list)
    language: str = "fr"
    question_count: int = 0
    source_count: int = 0
    representative_provenance: str = "observed"


@dataclass(frozen=True)
class DatasetBuildConfig:
    # "faithful" (default): preserve source formulations, group intents/variants.
    # "matrix": explicit experiment mode, persona x stage x specificity cross.
    mode: str = "faithful"
    # Lexical dedup of near-paraphrases: 0.65 merges common reformulations
    # while constraint tokens still split genuinely different needs.
    intent_similarity_threshold: float = 0.65
    personas: Sequence[str] = field(default_factory=list)
    stages: Sequence[str] = field(default_factory=lambda: DEFAULT_STAGES)
    specificity_levels: Sequence[int] = field(default_factory=lambda: DEFAULT_SPECIFICITY)
    candidates_per_cluster: int = 9
    brand_name: str = ""


def _question_items(cluster: ClusterInput) -> List[QuestionItem]:
    items = [QuestionItem(cluster.representative_question, cluster.representative_provenance)]
    for question in cluster.questions:
        if isinstance(question, QuestionItem):
            items.append(question)
        elif isinstance(question, Mapping):
            text = str(question.get("text", "")).strip()
            if text:
                items.append(QuestionItem(text, str(question.get("provenance", "observed"))))
        else:
            items.append(QuestionItem(str(question)))
    return items


def _constraint_tokens(text: str) -> frozenset:
    tokens = set(build_signature([text]).tokens)
    constraints = {token for token in tokens & _CONSTRAINT_TERMS}
    constraints.update(token for token in tokens if any(char.isdigit() for char in token))
    return frozenset(constraints)


def group_intents(items: Sequence[QuestionItem], threshold: float = 0.85) -> List[List[QuestionItem]]:
    """Greedy intent grouping: two formulations merge only when lexically close
    AND carrying the same budget/audience/numeric constraints."""
    intents: List[Dict] = []
    for item in items:
        signature = build_signature([item.text])
        constraints = _constraint_tokens(item.text)
        placed = False
        for intent in intents:
            if intent["constraints"] == constraints and signature_similarity(signature, intent["signature"]) >= threshold:
                intent["items"].append(item)
                placed = True
                break
        if not placed:
            intents.append({"signature": signature, "constraints": constraints, "items": [item]})
    return [intent["items"] for intent in intents]


class DatasetBuilder:
    def build(self, clusters: Iterable[ClusterInput], config: DatasetBuildConfig) -> List[PromptCandidate]:
        clusters = list(clusters)
        candidates = []
        for cluster in clusters:
            cluster_candidates = self.build_cluster(cluster, config)
            if cluster_candidates:
                candidates.extend(cluster_candidates)
        return candidates

    def build_cluster(self, cluster: ClusterInput, config: DatasetBuildConfig) -> List[PromptCandidate]:
        if config.mode == "matrix":
            return self._build_matrix(cluster, config)
        return self._build_faithful(cluster, config)

    def _build_faithful(self, cluster: ClusterInput, config: DatasetBuildConfig) -> List[PromptCandidate]:
        # Faithful mode: source formulations stay untouched (a short query stays
        # a short query), variants are grouped under one representative intent.
        items = [item for item in _question_items(cluster) if item.text.strip()]
        expected = self._expected_sub_intents(cluster)
        intents = group_intents(items, config.intent_similarity_threshold)
        candidates = []
        seen = set()
        # Intent coverage before variants: representatives of every admissible
        # intent come first; variants only fill the remaining per-cluster
        # budget. A paraphrase storm must not starve a distinct need.
        ordered = [item for intent_items in intents for item in intent_items[:1]]
        ordered += [item for intent_items in intents for item in intent_items[1:]]
        intent_index_by_id = {id(item): index for index, intent_items in enumerate(intents, start=1) for item in intent_items}
        # Inventory BEFORE the per-cluster cap: every admissible intent of this
        # cluster, even those whose candidates were truncated by
        # candidates_per_cluster. Coverage denominators read this, not the
        # intents that happened to survive the cap.
        cluster_intent_ids = [f"{cluster.id}:intent:{index}" for index in range(1, len(intents) + 1)]
        representative_text = {index: intent_items[0].text.strip() for index, intent_items in enumerate(intents, start=1)}
        first_of_intent = {id(intent_items[0]) for intent_items in intents if intent_items}
        for item in ordered:
            intent_index = intent_index_by_id[id(item)]
            rank = 0 if id(item) in first_of_intent else 1
            normalized = " ".join(item.text.casefold().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            is_representative = rank == 0
            candidates.append(PromptCandidate(
                text=item.text.strip(),
                provenance=PromptProvenance.OBSERVED if item.provenance == "observed" else PromptProvenance.TRANSFORMED,
                source_reference=cluster.id,
                confidence=0.9 if item.provenance == "observed" else 0.7,
                expected_fan_outs=expected,
                metadata={
                    "method": "intent_preserving",
                    "cluster_id": cluster.id,
                    "cluster_label": cluster.label,
                    "intent_id": f"{cluster.id}:intent:{intent_index}",
                    "is_representative": is_representative,
                    "variant_of": None if is_representative else representative_text[intent_index],
                    "cluster_intent_ids": cluster_intent_ids,
                    "original_provenance": item.provenance,
                    "language": cluster.language,
                    "cluster_question_count": cluster.question_count or len(cluster.questions) + 1,
                    "cluster_source_count": cluster.source_count,
                },
            ))
            if len(candidates) >= config.candidates_per_cluster:
                return candidates
        return candidates

    def _build_matrix(self, cluster: ClusterInput, config: DatasetBuildConfig) -> List[PromptCandidate]:
        personas = list(config.personas) or DEFAULT_PERSONAS.get(cluster.language, DEFAULT_PERSONAS["en"])
        combinations = product(personas, config.stages, config.specificity_levels)
        expected = self._expected_sub_intents(cluster)
        candidates = []
        seen = set()
        base_question = cluster.representative_question
        for persona, stage, specificity in combinations:
            prompt = self._render(base_question, persona, stage, specificity, cluster.language, expected)
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
        values = [cluster.representative_question] + [item.text for item in _question_items(cluster)[1:]]
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
