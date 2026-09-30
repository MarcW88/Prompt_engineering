import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from analysis.models import AnalysisRequest, PromptCandidate, PromptProvenance
from analysis.providers.brightdata import BrightDataProvider
from analysis.providers.oxylabs import OxylabsProvider
from analysis.reconstruction import PromptReconstructor, ReconstructionExample
from analysis.signatures import build_signature, signature_similarity
from analysis.validation import validate_candidate
from storage.analysis_storage import AnalysisStorage


FIXTURES = Path(__file__).parent / "fixtures"


class ProviderParsingTests(unittest.TestCase):
    def setUp(self):
        self.request = AnalysisRequest("Quelles chaussures de trail choisir ?")

    def test_brightdata_parser(self):
        raw = json.loads((FIXTURES / "brightdata_chatgpt.json").read_text())
        observation = BrightDataProvider(api_key="test", dataset_ids={"chatgpt": "test"}).parse_response(self.request, raw)
        self.assertEqual(observation.provider, "brightdata")
        self.assertEqual(len(observation.fan_outs), 3)
        self.assertEqual(observation.citations[0].url, "https://example.com/trail")

    def test_oxylabs_parser(self):
        raw = json.loads((FIXTURES / "oxylabs_chatgpt.json").read_text())
        observation = OxylabsProvider("test", "test").parse_response(self.request, raw)
        self.assertEqual(observation.provider, "oxylabs")
        self.assertEqual(len(observation.fan_outs), 3)
        self.assertEqual(len(observation.citations), 2)


class ReverseEngineeringTests(unittest.TestCase):
    def test_signature_similarity(self):
        left = build_signature(["meilleures chaussures trail débutant", "amorti chaussures trail"])
        right = build_signature(["chaussures trail pour débuter", "choisir amorti chaussures trail"])
        self.assertGreater(signature_similarity(left, right), 0.45)

    def test_reconstructs_from_nearest_signature(self):
        reconstructor = PromptReconstructor([
            ReconstructionExample("Quelles chaussures de trail choisir pour débuter ?", [
                "meilleures chaussures trail débutant", "amorti chaussures trail"
            ], "run-1")
        ])
        candidates = reconstructor.reconstruct(["chaussures trail pour débuter", "choisir amorti trail"])
        self.assertEqual(candidates[0].source_reference, "run-1")
        self.assertGreater(candidates[0].confidence, 0.4)

    def test_validation_and_storage(self):
        raw = json.loads((FIXTURES / "brightdata_chatgpt.json").read_text())
        request = AnalysisRequest("Quelles chaussures de trail choisir ?")
        observation = BrightDataProvider(api_key="test", dataset_ids={"chatgpt": "test"}).parse_response(request, raw)
        candidate = PromptCandidate(
            text=request.prompt,
            provenance=PromptProvenance.REVERSE_ENGINEERED,
            expected_fan_outs=["chaussures trail débutant", "amorti chaussures trail"],
        )
        scores = validate_candidate(candidate, observation)
        self.assertGreater(scores["fan_out_reproduction_score"], 0.5)
        with tempfile.TemporaryDirectory() as directory:
            storage = AnalysisStorage(str(Path(directory) / "analysis.db"))
            storage.save_candidate(candidate)
            storage.save_observation(observation, candidate.id)
            storage.save_validation(candidate.id, observation.id, scores)
            self.assertEqual(storage.list_candidates()[0].id, candidate.id)
            with sqlite3.connect(storage.db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fan_outs").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
