from typing import Callable, Dict, Iterable, List, Optional

from analysis.models import AnalysisObservation, PromptCandidate
from analysis.signatures import build_signature, signature_similarity
from analysis.validation import stability_score


def score_dataset_example(candidate: PromptCandidate, observations: Iterable[AnalysisObservation], similar_prompts: Iterable[str] = (), semantic_scorer: Optional[Callable[[List[str], List[str]], float]] = None) -> Dict[str, float]:
    observations = list(observations)
    if not observations:
        return {"coverage_score": 0.0, "stability_score": 0.0, "reproduction_score": 0.0, "redundancy_score": 0.0, "quality_score": 0.0}
    expected = build_signature(candidate.expected_fan_outs)
    # Reproduction is only measured on same-run provider-reported traces; a run
    # without exposed searches is "not_exposed", not a zero score.
    traced = [observation for observation in observations if observation.fan_outs]
    reproduction = (sum(signature_similarity(expected, build_signature(observation.fan_outs)) for observation in traced) / len(traced)) if traced else None
    observed_queries = {query.casefold() for observation in traced for query in observation.fan_outs}
    expected_queries = expected.normalized_queries
    # Mesure sémantique complémentaire (le lexical reste la référence) :
    # similarité moyenne du meilleur appariement attendu ↔ observé.
    semantic_reproduction = None
    if semantic_scorer is not None and expected_queries and observed_queries:
        try:
            semantic_reproduction = semantic_scorer(list(expected_queries), sorted(observed_queries))
        except Exception:
            semantic_reproduction = None
    coverage = sum(any(signature_similarity(build_signature([query]), build_signature([observed])) >= 0.45 for observed in observed_queries) for query in expected_queries) / len(expected_queries) if expected_queries and observed_queries else None
    stability = stability_score(observations)
    # Below two runs stability is unmeasured: it must not contribute a
    # fictitious perfect score to the acceptance quality. Its weight is
    # redistributed to the measured axes.
    prompt_signature = build_signature([candidate.text])
    similarities = [signature_similarity(prompt_signature, build_signature([prompt])) for prompt in similar_prompts if prompt != candidate.text]
    redundancy = max(similarities, default=0.0)
    has_fan_outs = any(observation.fan_outs for observation in observations)
    answer_score = sum(min(1.0, len(observation.answer or "") / 400) for observation in observations) / len(observations)
    avg_citations = sum(len(observation.citations) for observation in observations) / len(observations)
    citation_score = min(1.0, avg_citations / 3)
    stability_weight = 0.0 if stability is None else 1.0
    if has_fan_outs:
        quality = 0.35 * (coverage or 0.0) + 0.30 * (reproduction or 0.0) + 0.15 * (stability or 0.0) * stability_weight + 0.15 * answer_score + 0.05 * (1 - redundancy)
    else:
        # Engines like Google AI Mode never return fan-out queries: score the
        # answer itself and its citations instead of forcing coverage to 0.
        quality = 0.50 * answer_score + 0.25 * citation_score + 0.20 * (stability or 0.0) * stability_weight + 0.05 * (1 - redundancy)
    result = {
        "coverage_score": round(coverage, 4) if coverage is not None else None,
        "stability_score": round(stability, 4) if stability is not None else None,
        "reproduction_score": round(reproduction, 4) if reproduction is not None else None,
        "trace_status": "provider_reported" if has_fan_outs else "not_exposed",
        "redundancy_score": round(redundancy, 4),
        "quality_score": round(quality, 4),
    }
    if semantic_reproduction is not None:
        result["semantic_reproduction_score"] = round(semantic_reproduction, 4)
    return result
