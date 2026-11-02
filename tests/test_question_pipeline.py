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

    def test_marks_questions_from_client_own_channels_as_corporate(self):
        signals = [
            {"id": "s1", "source_type": "social", "platform": "linkedin", "url": "https://fr.linkedin.com/posts/be-life-naturalproducts_activity-123", "raw_text": "Be-Life soutient la plantation de haies.", "title": "Be-Life"},
            {"id": "s2", "source_type": "forum", "platform": "reddit", "url": "https://reddit.com/r/complements/xyz", "raw_text": "Quel magnésium choisir contre la fatigue ?", "title": "Quel magnésium choisir contre la fatigue ?"},
        ]
        questions = signals_to_questions(signals, "fr", lambda *_: ["Comment Be-Life agit-elle pour la biodiversité ?", "Pourquoi Be-Life choisit-elle les haies ?"], client_domain="be-life.eu", client_names=["Be-Life"])
        corporate = [q for q in questions if q.signal_id == "s1"]
        buyer = [q for q in questions if q.signal_id == "s2"]
        self.assertTrue(corporate and buyer)
        self.assertTrue(all(q.metadata["intent"] == "corporate" for q in corporate))
        self.assertTrue(all(q.metadata["intent"] == "buyer" for q in buyer))

    def test_corporate_only_cluster_is_not_geo_relevant(self):
        questions = [
            {"id": "q1", "text": "Comment Be-Life contribue-t-elle à la biodiversité ?", "metadata": {"intent": "corporate", "platform": "linkedin"}},
            {"id": "q2", "text": "Quels sont les avantages des haies selon Be-Life ?", "metadata": {"intent": "corporate", "platform": "linkedin"}},
        ]
        embeddings = [[1.0, 0.0], [0.99, 0.01]]
        clusters = cluster_questions(questions, embeddings, threshold=0.9, min_cluster_size=2)
        self.assertEqual(len(clusters), 1)
        self.assertFalse(clusters[0]["is_geo_relevant"])

    def test_singleton_buyer_question_is_geo_relevant(self):
        questions = [
            {"id": "q1", "text": "où acheter du magnésium bisglycinate en belgique ?", "metadata": {"intent": "buyer", "platform": "reddit"}},
            {"id": "q2", "text": "avis sur les chaussures de trail", "metadata": {"intent": "buyer", "platform": "forum"}},
        ]
        embeddings = [[1.0, 0.0], [0.0, 1.0]]
        clusters = cluster_questions(questions, embeddings, threshold=0.9, min_cluster_size=2)
        by_text = {cluster["representative_question"]: cluster["is_geo_relevant"] for cluster in clusters}
        # An interrogative singleton counts: it is a real buyer question asked
        # once — a non-interrogative fragment does not.
        self.assertTrue(by_text["où acheter du magnésium bisglycinate en belgique ?"])
        self.assertFalse(by_text["avis sur les chaussures de trail"])

    def test_mixed_cluster_stays_relevant_through_buyer_members(self):
        questions = [
            {"id": "q1", "text": "Pourquoi Be-Life sponsorise des haies ?", "metadata": {"intent": "corporate", "platform": "linkedin"}},
            {"id": "q2", "text": "où acheter les compléments Be-Life ?", "metadata": {"intent": "buyer", "platform": "serp"}},
        ]
        embeddings = [[1.0, 0.0], [0.99, 0.01]]
        clusters = cluster_questions(questions, embeddings, threshold=0.9, min_cluster_size=2)
        self.assertTrue(clusters[0]["is_geo_relevant"])

    def test_reconstructor_adapts_target_instead_of_copying_training_prompt(self):
        reference = "Quelles chaussures de trail choisir ?"
        reconstructor = PromptReconstructor([ReconstructionExample(reference, ["chaussures trail", "amorti trail"], "p1")])
        candidate = reconstructor.reconstruct(["chaussures trail terrain humide", "adhérence trail"], "fr", 1)[0]
        self.assertNotEqual(candidate.text, reference)
        self.assertIn("chaussures trail terrain humide", candidate.text)
        self.assertEqual(candidate.metadata["method"], "nearest_fan_out_signature")


if __name__ == "__main__":
    unittest.main()
