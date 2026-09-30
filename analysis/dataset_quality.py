from typing import Dict, Iterable, List

from analysis.models import AnalysisObservation, PromptCandidate
from analysis.signatures import build_signature, signature_similarity
from analysis.validation import stability_score


def score_dataset_example(candidate: PromptCandidate, observations: Iterable[AnalysisObservation], similar_prompts: Iterable[str] = ()) -> Dict[str, float]:
    observations = list(observations)
    if not observations:
        return {"coverage_score": 0.0, "stability_score": 0.0, "reproduction_score": 0.0, "redundancy_score": 0.0, "quality_score": 0.0}
    expected = build_signature(candidate.expected_fan_outs)
    reproduction = sum(signature_similarity(expected, build_signature(observation.fan_outs)) for observation in observations) / len(observations)
    observed_queries = {query.casefold() for observation in observations for query in observation.fan_outs}
    expected_queries = expected.normalized_queries
    coverage = sum(any(signature_similarity(build_signature([query]), build_signature([observed])) >= 0.45 for observed in observed_queries) for query in expected_queries) / len(expected_queries) if expected_queries else 0.0
    stability = stability_score(observations)
    prompt_signature = build_signature([candidate.text])
    similarities = [signature_similarity(prompt_signature, build_signature([prompt])) for prompt in similar_prompts if prompt != candidate.text]
    redundancy = max(similarities, default=0.0)
    quality = 0.4 * coverage + 0.35 * reproduction + 0.2 * stability + 0.05 * (1 - redundancy)
    return {
        "coverage_score": round(coverage, 4),
        "stability_score": round(stability, 4),
        "reproduction_score": round(reproduction, 4),
        "redundancy_score": round(redundancy, 4),
        "quality_score": round(quality, 4),
    }
