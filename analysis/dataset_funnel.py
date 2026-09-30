import math
from collections import defaultdict
from typing import Dict, Iterable, List

from analysis.models import PromptCandidate
from analysis.signatures import query_similarity


def pre_execution_score(candidate: PromptCandidate, cluster_candidates: Iterable[PromptCandidate] = ()) -> Dict[str, float]:
    metadata = candidate.metadata
    question_count = max(1, int(metadata.get("cluster_question_count", 1)))
    source_count = max(0, int(metadata.get("cluster_source_count", 0)))
    specificity = int(metadata.get("specificity_level", 0))
    stage = metadata.get("stage", "discovery")
    signal_strength = min(1.0, math.log1p(question_count) / math.log(11))
    source_diversity = min(1.0, source_count / 3)
    sub_intent_coverage = min(1.0, len(candidate.expected_fan_outs) / 5)
    business_value = 1.0 if stage == "comparison" else 0.65
    specificity_score = {0: 0.55, 1: 0.85, 2: 1.0}.get(specificity, 0.6)
    similarities = [query_similarity(candidate.text, other.text) for other in cluster_candidates if other.id != candidate.id]
    redundancy = max(similarities, default=0.0)
    score = 0.25 * signal_strength + 0.2 * source_diversity + 0.2 * sub_intent_coverage + 0.15 * business_value + 0.15 * specificity_score + 0.05 * (1 - redundancy)
    return {
        "pre_execution_score": round(score, 4),
        "signal_strength": round(signal_strength, 4),
        "source_diversity": round(source_diversity, 4),
        "sub_intent_coverage": round(sub_intent_coverage, 4),
        "business_value": round(business_value, 4),
        "specificity_score": round(specificity_score, 4),
        "redundancy_score": round(redundancy, 4),
    }


def score_candidates(candidates: Iterable[PromptCandidate]) -> List[PromptCandidate]:
    candidates = list(candidates)
    by_cluster = defaultdict(list)
    for candidate in candidates:
        by_cluster[candidate.source_reference].append(candidate)
    for candidate in candidates:
        scores = pre_execution_score(candidate, by_cluster[candidate.source_reference])
        candidate.metadata.update(scores)
        candidate.confidence = scores["pre_execution_score"]
    return candidates


def stratified_sample(candidates: Iterable[PromptCandidate], sample_size: int, max_per_cluster: int = 5) -> List[PromptCandidate]:
    groups = defaultdict(list)
    for candidate in candidates:
        groups[candidate.source_reference].append(candidate)
    for group in groups.values():
        group.sort(key=lambda candidate: (-candidate.confidence, candidate.metadata.get("persona", ""), candidate.metadata.get("stage", ""), candidate.metadata.get("specificity_level", 0)))
    selected = []
    used_dimensions = defaultdict(set)
    while len(selected) < sample_size:
        progress = False
        for cluster_id in sorted(groups, key=lambda key: -max((candidate.confidence for candidate in groups[key]), default=0)):
            if len([candidate for candidate in selected if candidate.source_reference == cluster_id]) >= max_per_cluster:
                continue
            group = groups[cluster_id]
            if not group:
                continue
            dimensions = used_dimensions[cluster_id]
            diverse_index = next((index for index, candidate in enumerate(group) if (candidate.metadata.get("persona"), candidate.metadata.get("stage"), candidate.metadata.get("specificity_level")) not in dimensions), 0)
            candidate = group.pop(diverse_index)
            selected.append(candidate)
            dimensions.add((candidate.metadata.get("persona"), candidate.metadata.get("stage"), candidate.metadata.get("specificity_level")))
            progress = True
            if len(selected) >= sample_size:
                break
        if not progress:
            break
    return selected


def estimate_cost(executed_prompts: int, repetitions: int, engines: int, cost_per_execution_eur: float) -> Dict[str, float]:
    executions = max(0, executed_prompts) * max(0, repetitions) * max(0, engines)
    return {"executions": executions, "estimated_cost_eur": round(executions * max(0.0, cost_per_execution_eur), 2)}
