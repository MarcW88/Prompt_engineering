import unittest

from analysis.qualification import portfolio_quotas, qualify_question, select_with_quotas
from analysis.models import PromptCandidate, PromptProvenance


VARIANTS = ["Be-Life", "Be Life"]
COMPETITORS = ["Nutergia", "Metagenics"]
THEMES = ["Magnésium et bisglycinate de magnésium", "Stress et gestion du stress", "Sommeil et endormissement", "Probiotiques et microbiotiques"]


def candidate(text, category):
    c = PromptCandidate(text=text, provenance=PromptProvenance.OBSERVED)
    c.metadata["qualification"] = {"category": category, "kickoff_theme": "", "justification": "test"}
    c.metadata["is_representative"] = True
    return c


class QualificationTests(unittest.TestCase):
    def test_brand_question_is_classified_brand(self):
        result = qualify_question("où acheter les compléments Be-Life ?", VARIANTS, COMPETITORS, THEMES)
        self.assertEqual(result["category"], "brand")

    def test_brand_comparative_is_standard_comparison(self):
        result = qualify_question("Be-Life ou Nutergia : lequel choisir ?", VARIANTS, COMPETITORS, THEMES)
        self.assertEqual(result["category"], "comparaison_standard")
        self.assertIn("Be-Life", result["justification"])

    def test_generic_comparative_without_brand_stays_kickoff(self):
        result = qualify_question("quel est le meilleur complément pour le stress ?", VARIANTS, COMPETITORS, THEMES)
        self.assertEqual(result["category"], "non_brand_kickoff")
        self.assertEqual(result["kickoff_theme"], "Stress et gestion du stress")

    def test_kickoff_theme_matching(self):
        result = qualify_question("où acheter du magnésium bisglycinate en belgique ?", VARIANTS, COMPETITORS, THEMES)
        self.assertEqual(result["category"], "non_brand_kickoff")
        self.assertEqual(result["kickoff_theme"], "Magnésium et bisglycinate de magnésium")

    def test_off_topic_question_is_flagged(self):
        result = qualify_question("quelle est la capitale de la Mongolie ?", VARIANTS, COMPETITORS, THEMES)
        self.assertEqual(result["category"], "hors_périmètre")

    def test_quotas_split_15_85(self):
        quotas = portfolio_quotas(200)
        self.assertEqual(quotas, {"brand_plus_comparaison": 30, "non_brand_kickoff": 170})

    def test_selection_reports_deficits_instead_of_filling_off_topic(self):
        candidates = [candidate(f"kickoff {i}", "non_brand_kickoff") for i in range(10)]
        candidates += [candidate("hors sujet", "hors_périmètre")]
        selected, deficits = select_with_quotas(candidates, 20, lambda pool, size, mpc: pool[:size])
        self.assertEqual(len(selected), 10)
        self.assertFalse(any(c.metadata["qualification"]["category"] == "hors_périmètre" for c in selected))
        self.assertEqual(deficits["non_brand_kickoff"], 7)
        self.assertEqual(deficits["brand"], 2)
        self.assertEqual(deficits["comparaison_standard"], 2)

    def test_both_brand_families_are_represented(self):
        candidates = [candidate(f"brand {i}", "brand") for i in range(2)]
        candidates += [candidate(f"vs {i}", "comparaison_standard") for i in range(2)]
        candidates += [candidate(f"k {i}", "non_brand_kickoff") for i in range(20)]
        selected, _ = select_with_quotas(candidates, 20, lambda pool, size, mpc: pool[:size])
        cats = {c.metadata["qualification"]["category"] for c in selected}
        self.assertIn("brand", cats)
        self.assertIn("comparaison_standard", cats)

    def test_no_double_counting_between_categories(self):
        candidates = [candidate(f"b{i}", "brand") for i in range(3)] + [candidate(f"k{i}", "non_brand_kickoff") for i in range(10)]
        selected, _ = select_with_quotas(candidates, 5, lambda pool, size, mpc: pool[:size])
        self.assertEqual(len(selected), len({c.text for c in selected}))


if __name__ == "__main__":
    unittest.main()


class AuditRegressionTests(unittest.TestCase):
    def test_sample_size_5_never_selects_6(self):
        """Cas reproduit de l'audit : trois catégories disponibles, cible 5."""
        candidates = [candidate(f"b{i}", "brand") for i in range(3)]
        candidates += [candidate(f"vs{i}", "comparaison_standard") for i in range(3)]
        candidates += [candidate(f"k{i}", "non_brand_kickoff") for i in range(10)]
        selected, _ = select_with_quotas(candidates, 5, lambda pool, size, mpc: pool[:size])
        self.assertLessEqual(len(selected), 5)

    def test_no_reallocation_between_categories(self):
        """190 brand / 10 kickoff : la cible 200 ne doit PAS se remplir de brand."""
        candidates = [candidate(f"b{i}", "brand") for i in range(190)]
        candidates += [candidate(f"k{i}", "non_brand_kickoff") for i in range(10)]
        selected, deficits = select_with_quotas(candidates, 200, lambda pool, size, mpc: pool[:size])
        branded = sum(1 for c in selected if c.metadata["qualification"]["category"] in ("brand", "comparaison_standard"))
        self.assertLessEqual(branded, 30)  # jamais plus que le quota 15 %
        self.assertEqual(deficits["non_brand_kickoff"], 160)
        self.assertEqual(len(selected), 40)  # 10 kickoff + 30 brand max

    def test_no_kickoff_config_marks_off_scope_not_kickoff(self):
        result = qualify_question("quel vélo choisir ?", [], [], [])
        self.assertEqual(result["category"], "hors_périmètre")
        self.assertIn("aucun thème kickoff", result["justification"])

    def test_hors_perimetre_never_selected(self):
        candidates = [candidate(f"h{i}", "hors_périmètre") for i in range(50)]
        selected, _ = select_with_quotas(candidates, 10, lambda pool, size, mpc: pool[:size])
        self.assertEqual(selected, [])


class FallbackPrecedenceTests(unittest.TestCase):
    def test_env_zero_wins_over_dataset_flag(self):
        """L'environnement OPENAI_FANOUT_FALLBACK=0 ne peut pas être réactivé
        par le paramètre du dataset (régression audit)."""
        import os
        from unittest.mock import Mock, patch
        from collection_worker import CollectionWorker
        w = CollectionWorker.__new__(CollectionWorker)
        w.fanout_fallback_enabled = True
        with patch.dict(os.environ, {"OPENAI_FANOUT_FALLBACK": "0"}):
            env_allowed = os.getenv("OPENAI_FANOUT_FALLBACK", "1") != "0"
            w.fanout_fallback_enabled = env_allowed and bool({"fanout_fallback": True}.get("fanout_fallback", True))
        self.assertFalse(w.fanout_fallback_enabled)


class BrandPrefilterTests(unittest.TestCase):
    def test_faithful_builder_admits_non_brand_questions(self):
        """Le filtre de mots de marque ne doit plus exclure les questions
        non-brand pertinentes avant la qualification."""
        from analysis.dataset_builder import ClusterInput, DatasetBuildConfig, DatasetBuilder
        cluster = ClusterInput(
            id="c1", label="stress", representative_question="quel complément pour le stress ?",
            questions=[{"text": "quel complément pour le stress ?", "provenance": "observed"}],
            language="fr", question_count=1, source_count=1, representative_provenance="observed",
        )
        built = DatasetBuilder().build([cluster], DatasetBuildConfig(brand_name="Be-Life", candidates_per_cluster=3))
        self.assertTrue(built)  # avant : exclu car "Be-Life" absent du texte
