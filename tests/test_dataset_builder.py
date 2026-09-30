import unittest

from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder
from analysis.dataset_quality import score_dataset_example
from analysis.models import AnalysisObservation, Citation


class DatasetBuilderTests(unittest.TestCase):
    def setUp(self):
        self.cluster = ClusterInput(
            id="cluster-1",
            label="trail_beginner",
            representative_question="Quelles chaussures de trail choisir pour débuter ?",
            questions=[
                "Quelles chaussures de trail choisir sur terrain humide ?",
                "Quel amorti choisir pour débuter le trail ?",
            ],
            language="fr",
        )

    def test_builds_controlled_matrix_with_traceability(self):
        candidates = DatasetBuilder().build([self.cluster], DatasetBuildConfig(
            personas=["débutant", "petit budget"], stages=["discovery", "comparison"],
            specificity_levels=[0, 2], candidates_per_cluster=8,
        ))
        self.assertEqual(len(candidates), 8)
        self.assertEqual(candidates[0].source_reference, "cluster-1")
        self.assertEqual(candidates[0].metadata["method"], "controlled_matrix")
        self.assertEqual(len({candidate.text for candidate in candidates}), 8)
        self.assertEqual(len(candidates[0].expected_fan_outs), 3)

    def test_respects_candidate_limit(self):
        candidates = DatasetBuilder().build_cluster(self.cluster, DatasetBuildConfig(candidates_per_cluster=4))
        self.assertEqual(len(candidates), 4)

    def test_scores_high_quality_repeated_observations(self):
        candidate = DatasetBuilder().build_cluster(self.cluster, DatasetBuildConfig(candidates_per_cluster=1))[0]
        fan_outs = list(candidate.expected_fan_outs)
        observations = [AnalysisObservation(
            prompt=candidate.text, provider="fixture", engine="chatgpt", fan_outs=fan_outs,
            citations=[Citation("https://example.com/trail")],
        ) for _ in range(3)]
        scores = score_dataset_example(candidate, observations)
        self.assertGreater(scores["stability_score"], 0.9)
        self.assertGreater(scores["quality_score"], 0.5)

    def test_scores_empty_observations_as_zero(self):
        candidate = DatasetBuilder().build_cluster(self.cluster, DatasetBuildConfig(candidates_per_cluster=1))[0]
        self.assertEqual(score_dataset_example(candidate, [])["quality_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
