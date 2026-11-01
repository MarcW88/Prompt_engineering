import unittest

from analysis.baseline_eval import HeldOutTarget, evaluate_held_out, nearest_baseline
from analysis.reconstruction import ReconstructionExample


class BaselineEvalTests(unittest.TestCase):
    def setUp(self):
        self.examples = [
            ReconstructionExample(prompt="chaussures trail débutant", fan_outs=["chaussures trail", "trail débutant"], source_reference="p1", engine="chatgpt"),
            ReconstructionExample(prompt="tente bivouac légère", fan_outs=["tente bivouac", "bivouac ultra léger"], source_reference="p2", engine="chatgpt"),
        ]

    def test_nearest_baseline_picks_closest_example(self):
        self.assertEqual(
            nearest_baseline(["tente bivouac", "bivouac 2 places"], self.examples),
            "tente bivouac légère")

    def test_nearest_baseline_excludes_quasi_variant(self):
        # Le prompt cible quasi-identique à un exemple est exclu (même règle que l'ICL).
        result = nearest_baseline(["chaussures trail"], self.examples, target_prompt="chaussures trail débutant")
        self.assertEqual(result, "tente bivouac légère")

    def test_evaluation_compares_methods_honestly(self):
        targets = [
            HeldOutTarget("t1", ["requête a", "requête b"],
                icl_candidates=[{"prompt": "c1", "observed_queries": ["requête a", "requête b"]},
                                {"prompt": "c2", "observed_queries": None}],
                baseline_candidates=[{"prompt": "b1", "observed_queries": ["requête a"]}]),
            HeldOutTarget("t2", ["requête c"],
                icl_candidates=[{"prompt": "c3", "observed_queries": None}],
                baseline_candidates=[]),
        ]
        result = evaluate_held_out(targets)
        self.assertEqual(result["targets_total"], 2)
        self.assertEqual(result["icl_evaluable"], 1)
        self.assertEqual(result["baseline_evaluable"], 1)
        self.assertEqual(result["paired_evaluable"], 1)
        self.assertEqual(result["icl_reproduced"], 1)
        self.assertGreater(result["icl_mean_best"], result["baseline_mean_best"])
        # Les candidats non exécutés sont exclus, pas notés zéro.
        self.assertIsNone(result["per_target"][1]["icl_best"])

    def test_empty_held_out_is_honest(self):
        result = evaluate_held_out([])
        self.assertEqual(result["targets_total"], 0)
        self.assertIsNone(result["icl_mean_best"])


if __name__ == "__main__":
    unittest.main()
