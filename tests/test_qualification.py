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
        self.assertEqual(deficits["brand_plus_comparaison"], 3)

    def test_no_double_counting_between_categories(self):
        candidates = [candidate(f"b{i}", "brand") for i in range(3)] + [candidate(f"k{i}", "non_brand_kickoff") for i in range(10)]
        selected, _ = select_with_quotas(candidates, 5, lambda pool, size, mpc: pool[:size])
        self.assertEqual(len(selected), len({c.text for c in selected}))


if __name__ == "__main__":
    unittest.main()
