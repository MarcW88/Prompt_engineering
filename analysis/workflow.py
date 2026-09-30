from typing import Dict, Iterable, List

from analysis.models import AnalysisObservation, AnalysisRequest, PromptCandidate
from analysis.providers.base import AnalysisProvider
from analysis.validation import validate_candidate
from storage.analysis_storage import AnalysisStorage


class ReverseEngineeringWorkflow:
    def __init__(self, providers: Dict[str, AnalysisProvider], storage: AnalysisStorage):
        self.providers = providers
        self.storage = storage

    def observe(self, requests: Iterable[AnalysisRequest], provider_name: str) -> List[AnalysisObservation]:
        provider = self.providers[provider_name]
        observations = provider.execute_many(requests)
        for observation in observations:
            self.storage.save_observation(observation)
        return observations

    def validate(self, candidate: PromptCandidate, provider_name: str, engine: str,
                 country: str = "FR", language: str = "fr", repetitions: int = 1):
        provider = self.providers[provider_name]
        self.storage.save_candidate(candidate)
        observations = []
        for _ in range(max(1, repetitions)):
            observation = provider.execute(AnalysisRequest(
                prompt=candidate.text,
                engine=engine,
                country=country,
                language=language,
                metadata={"candidate_id": candidate.id, "validation": True},
            ))
            self.storage.save_observation(observation, candidate.id)
            observations.append(observation)
        scores = validate_candidate(candidate, observations[0], observations[1:])
        self.storage.save_validation(candidate.id, observations[0].id, scores)
        return observations, scores
