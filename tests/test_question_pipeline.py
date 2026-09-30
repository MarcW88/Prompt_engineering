import unittest

from analysis.question_pipeline import cluster_questions, signals_to_questions
from analysis.reconstruction import PromptReconstructor, ReconstructionExample


class QuestionPipelineTests(unittest.TestCase):
    def test_preserves_observed_serp_and_gsc_questions(self):
        signals = [
            {"id": "s1", "source_type": "serp", "platform": "google_paa", "raw_text": "Quel vélo choisir ?", "title": "Quel vélo choisir ?"},
            {"id": "s2", "source_type": "gsc_conversation", "platform": "google_search_console", "raw_text": "Comment choisir un vélo électrique pour aller au travail ?", "title": ""},
        ]
        questions = signals_to_questions(signals, "fr", lambda *_: self.fail("transformer should not run"))
        self.assertEqual(len(questions), 2)
        self.assertTrue(all(question.provenance == "observed" for question in questions))
        self.assertTrue(all(question.confidence == 1.0 for question in questions))

    def test_transforms_non_question_discussions(self):
        signals = [{"id": "s1", "source_type": "forum", "platform": "reddit", "raw_text": "Je débute le trail et les chemins sont boueux.", "title": "Besoin de conseils"}]
        questions = signals_to_questions(signals, "fr", lambda *_: ["Quelles chaussures choisir pour débuter le trail sur terrain boueux ?"])
        self.assertEqual(questions[0].provenance, "transformed")
        self.assertEqual(questions[0].confidence, 0.7)

    def test_clusters_similar_questions_and_selects_representative(self):
        questions = [
            {"id": "q1", "text": "chaussures trail débutant", "metadata": {"platform": "gsc"}},
            {"id": "q2", "text": "quelles chaussures trail pour débuter", "metadata": {"platform": "reddit"}},
            {"id": "q3", "text": "tente légère randonnée", "metadata": {"platform": "paa"}},
        ]
        embeddings = [[1.0, 0.0], [0.98, 0.02], [0.0, 1.0]]
        clusters = cluster_questions(questions, embeddings, threshold=0.9, min_cluster_size=2)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["question_count"], 2)
        self.assertTrue(clusters[0]["is_geo_relevant"])
        self.assertEqual(len(clusters[0]["members"]), 2)

    def test_reconstructor_adapts_target_instead_of_copying_training_prompt(self):
        reference = "Quelles chaussures de trail choisir ?"
        reconstructor = PromptReconstructor([ReconstructionExample(reference, ["chaussures trail", "amorti trail"], "p1")])
        candidate = reconstructor.reconstruct(["chaussures trail terrain humide", "adhérence trail"], "fr", 1)[0]
        self.assertNotEqual(candidate.text, reference)
        self.assertIn("chaussures trail terrain humide", candidate.text)
        self.assertEqual(candidate.metadata["method"], "nearest_fan_out_signature")


if __name__ == "__main__":
    unittest.main()
