from typing import Dict, Iterable, List, Set
from urllib.parse import urlparse

from analysis.models import AnalysisObservation, PromptCandidate
from analysis.signatures import build_signature, signature_similarity


def citation_domains(observation: AnalysisObservation) -> Set[str]:
    return {urlparse(citation.url).netloc.casefold().removeprefix("www.") for citation in observation.citations if citation.url}


def set_similarity(left: Set[str], right: Set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def stability_score(observations: Iterable[AnalysisObservation]) -> float:
    observations = list(observations)
    if len(observations) < 2:
        return 1.0
    scores = []
    for index, left in enumerate(observations):
        for right in observations[index + 1:]:
            fan_out_score = signature_similarity(build_signature(left.fan_outs), build_signature(right.fan_outs))
            citation_score = set_similarity(citation_domains(left), citation_domains(right))
            scores.append((fan_out_score + citation_score) / 2)
    return sum(scores) / len(scores) if scores else 1.0


def validate_candidate(candidate: PromptCandidate, observation: AnalysisObservation,
                       repetitions: Iterable[AnalysisObservation] = ()) -> Dict[str, float]:
    fan_out_score = signature_similarity(
        build_signature(candidate.expected_fan_outs),
        build_signature(observation.fan_outs),
    )
    expected_domains = set(candidate.metadata.get("expected_citation_domains", []))
    citation_score = set_similarity(expected_domains, citation_domains(observation)) if expected_domains else 0.0
    repeated = [observation, *list(repetitions)]
    stable = stability_score(repeated)
    return {
        "fan_out_reproduction_score": round(fan_out_score, 4),
        "citation_overlap_score": round(citation_score, 4),
        "stability_score": round(stable, 4),
        "overall_score": round(0.7 * fan_out_score + 0.3 * stable, 4),
    }
