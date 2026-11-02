import unittest

from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder, QuestionItem, group_intents
from analysis.dataset_quality import score_dataset_example
from analysis.models import AnalysisObservation, Citation, PromptProvenance


class DatasetBuilderTests(unittest.TestCase):
    def setUp(self):
        self.cluster = ClusterInput(
            id="cluster-1",
            label="trail_beginner",
            representative_question="Quelles chaussures de trail choisir pour débuter ?",
            questions=[
                QuestionItem("Quelles chaussures de trail choisir sur terrain humide ?", "transformed"),
                "Quel amorti choisir pour débuter le trail ?",
            ],
            language="fr",
        )

    def test_faithful_mode_preserves_formulations(self):
        candidates = DatasetBuilder().build([self.cluster], DatasetBuildConfig(candidates_per_cluster=9))
        self.assertEqual(len(candidates), 3)
        texts = {candidate.text for candidate in candidates}
        self.assertIn("Quelles chaussures de trail choisir pour débuter ?", texts)
        self.assertIn("Quelles chaussures de trail choisir sur terrain humide ?", texts)
        # Pas de préambule persona ni de demande de réponse détaillée.
        for candidate in candidates:
            self.assertNotIn("Je suis", candidate.text)
            self.assertNotIn("Aide-moi", candidate.text)
        by_text = {candidate.text: candidate for candidate in candidates}
        self.assertEqual(by_text["Quelles chaussures de trail choisir pour débuter ?"].provenance, PromptProvenance.OBSERVED)
        self.assertEqual(by_text["Quelles chaussures de trail choisir sur terrain humide ?"].provenance, PromptProvenance.TRANSFORMED)

    def test_faithful_mode_keeps_short_expressions(self):
        cluster = ClusterInput(id="c", label="q", representative_question="trail running définition",
            questions=["Quelle différence entre trail et course sur route ?"], language="fr")
        candidates = DatasetBuilder().build([cluster], DatasetBuildConfig())
        texts = [candidate.text for candidate in candidates]
        self.assertIn("trail running définition", texts)
        self.assertIn("Quelle différence entre trail et course sur route ?", texts)

    def test_intent_grouping_merges_paraphrases_keeps_constraints(self):
        items = [
            QuestionItem("Quelle différence entre trail et course sur route ?"),
            QuestionItem("Différence entre le trail et la course sur route ?"),
            QuestionItem("Quelles chaussures de trail pour un budget de 100 euros ?"),
            QuestionItem("Quelles chaussures de trail pour un budget de 200 euros ?"),
        ]
        intents = group_intents(items, 0.65)
        sizes = sorted(len(intent) for intent in intents)
        self.assertEqual(len(intents), 3)
        self.assertEqual(sizes, [1, 1, 2])

    def test_faithful_variants_share_intent(self):
        cluster = ClusterInput(id="c", label="q", representative_question="Quelle différence entre trail et course sur route ?",
            questions=["Différence entre le trail et la course sur route ?", "Quel amorti choisir pour débuter le trail ?"], language="fr")
        candidates = DatasetBuilder().build([cluster], DatasetBuildConfig(intent_similarity_threshold=0.65))
        by_text = {candidate.text: candidate for candidate in candidates}
        paraphrase = by_text["Différence entre le trail et la course sur route ?"]
        self.assertFalse(paraphrase.metadata["is_representative"])
        self.assertEqual(paraphrase.metadata["variant_of"], "Quelle différence entre trail et course sur route ?")
        other = by_text["Quel amorti choisir pour débuter le trail ?"]
        self.assertTrue(other.metadata["is_representative"])
        self.assertNotEqual(paraphrase.metadata["intent_id"], other.metadata["intent_id"])

    def test_variants_do_not_saturate_the_cap(self):
        # 6 paraphrases de la même intention + 1 intention à contrainte : le
        # représentant de l'intention contrainte doit survivre au plafond.
        items = ["trail débutant", "trail pour débutant", "trail débutant conseils",
                 "trail débutant guide", "trail débutant équipement", "trail débutant avis",
                 "trail expert montagne 3000m"]
        cluster = ClusterInput(id="c", label="trail", representative_question=items[0],
            questions=items[1:], question_count=7, source_count=2)
        candidates = DatasetBuilder().build([cluster], DatasetBuildConfig(candidates_per_cluster=2))
        self.assertEqual(len(candidates), 2)
        texts = [candidate.text for candidate in candidates]
        self.assertIn("trail débutant", texts)
        self.assertIn("trail expert montagne 3000m", texts)
        self.assertTrue(all(c.metadata["is_representative"] for c in candidates))

    def test_intent_inventory_precedes_per_cluster_cap(self):
        # Cap=1 tronque la seconde intention distincte, mais l'inventaire
        # pré-plafond doit quand même la compter.
        items = ["trail débutant", "nutrition course ultra distance 100km"]
        cluster = ClusterInput(id="c", label="mix", representative_question=items[0],
            questions=items[1:], question_count=2, source_count=2)
        candidates = DatasetBuilder().build([cluster], DatasetBuildConfig(candidates_per_cluster=1, intent_similarity_threshold=0.65))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].metadata["cluster_intent_ids"], ["c:intent:1", "c:intent:2"])

    def test_global_pool_cap_keeps_every_intent(self):
        # Reproduit l'audit : plafond global 2, cluster 1 saturé de paraphrases,
        # cluster 2 avec une intention distincte → les deux représentants
        # doivent survivre, la variante est évincée.
        from analysis.dataset_funnel import intent_first_order
        clusters = [
            ClusterInput(id="c1", label="a", representative_question="trail débutant",
                questions=["trail débutant guide", "trail débutant conseils"], question_count=3, source_count=1),
            ClusterInput(id="c2", label="b", representative_question="trail expert montagne 3000m",
                questions=[], question_count=1, source_count=1),
        ]
        built = DatasetBuilder().build(clusters, DatasetBuildConfig())
        # Vérification préalable : les variantes partagent bien la même intention.
        self.assertEqual(len({c.metadata["intent_id"] for c in built if c.metadata["cluster_id"] == "c1"}), 1)
        capped = intent_first_order(built)[:2]
        texts = [candidate.text for candidate in capped]
        self.assertIn("trail débutant", texts)
        self.assertIn("trail expert montagne 3000m", texts)

    def test_matrix_mode_remains_explicit(self):
        candidates = DatasetBuilder().build([self.cluster], DatasetBuildConfig(
            mode="matrix", personas=["débutant", "petit budget"], stages=["discovery", "comparison"],
            specificity_levels=[0, 2], candidates_per_cluster=8,
        ))
        self.assertEqual(len(candidates), 8)
        self.assertEqual(candidates[0].source_reference, "cluster-1")
        self.assertEqual(candidates[0].metadata["method"], "controlled_matrix")
        self.assertEqual(len({candidate.text for candidate in candidates}), 8)
        self.assertEqual(len(candidates[0].expected_fan_outs), 3)

    def test_respects_candidate_limit(self):
        candidates = DatasetBuilder().build_cluster(self.cluster, DatasetBuildConfig(candidates_per_cluster=2))
        self.assertEqual(len(candidates), 2)

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

    def test_unexposed_traces_are_not_zero_reproduction(self):
        candidate = DatasetBuilder().build_cluster(self.cluster, DatasetBuildConfig(candidates_per_cluster=1))[0]
        observations = [AnalysisObservation(prompt=candidate.text, provider="fixture", engine="chatgpt", answer="réponse " * 100)]
        scores = score_dataset_example(candidate, observations)
        self.assertIsNone(scores["reproduction_score"])
        self.assertEqual(scores["trace_status"], "not_exposed")

    def test_scores_empty_observations_as_zero(self):
        candidate = DatasetBuilder().build_cluster(self.cluster, DatasetBuildConfig(candidates_per_cluster=1))[0]
        self.assertEqual(score_dataset_example(candidate, [])["quality_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
