import unittest

from analysis.dataset_funnel import estimate_cost, score_candidates, stratified_sample
from analysis.models import PromptCandidate, PromptProvenance


def candidate(cluster, persona, stage, specificity, questions=5, sources=2):
    return PromptCandidate(
        text=f"{cluster} {persona} {stage} {specificity}",
        provenance=PromptProvenance.SYNTHETIC,
        source_reference=cluster,
        expected_fan_outs=[f"{cluster} besoin {index}" for index in range(4)],
        metadata={"persona": persona, "stage": stage, "specificity_level": specificity, "cluster_question_count": questions, "cluster_source_count": sources},
    )


class DatasetFunnelTests(unittest.TestCase):
    def test_scores_candidates_without_execution(self):
        candidates = score_candidates([
            candidate("trail", "débutant", "comparison", 2, 10, 3),
            candidate("trail", "expert", "discovery", 0, 2, 1),
        ])
        self.assertGreater(candidates[0].confidence, candidates[1].confidence)
        self.assertIn("pre_execution_score", candidates[0].metadata)

    def test_stratified_sample_covers_clusters_and_limits_dominance(self):
        candidates = score_candidates([
            *[candidate("trail", f"p{i}", "comparison", i % 3, 10, 3) for i in range(8)],
            *[candidate("camping", f"p{i}", "discovery", i % 3, 3, 2) for i in range(4)],
            *[candidate("cycling", f"p{i}", "comparison", i % 3, 2, 1) for i in range(4)],
        ])
        selected = stratified_sample(candidates, 9, max_per_cluster=4)
        counts = {cluster: sum(item.source_reference == cluster for item in selected) for cluster in {item.source_reference for item in selected}}
        self.assertEqual(len(selected), 9)
        self.assertEqual(set(counts), {"trail", "camping", "cycling"})
        self.assertLessEqual(max(counts.values()), 4)

    def test_estimates_and_caps_execution_cost_inputs(self):
        estimate = estimate_cost(100, 3, 2, 0.02)
        self.assertEqual(estimate["executions"], 600)
        self.assertEqual(estimate["estimated_cost_eur"], 12.0)


if __name__ == "__main__":
    unittest.main()
