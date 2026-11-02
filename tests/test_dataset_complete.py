import unittest

from analysis.dataset_complete import (
    Batch, CoverageCell, build_kickoff_context, completed_batch_ids,
    compute_coverage, input_version, plan_batches, proposed_rows, run_batches,
)
from analysis.elmo_adapter import clean_domain, dedupe_key, infer_brand_name, normalize_prompts


def q(text, provenance="observed", category="non_brand_kickoff", theme="Stress et gestion du stress", intent="buyer", batch=None):
    meta = {"intent": intent, "qualification": {"category": category, "kickoff_theme": theme}}
    if batch:
        meta["batch_id"] = batch
    return {"text": text, "provenance": provenance, "metadata": meta}


CONFIG = {"themes": ["Stress et gestion du stress", "Sommeil et endormissement"],
          "competitors": ["Nutergia", "PiLeJe"], "brand_variants": ["Be-Life"], "domain": "be-life.eu"}


class ElmoAdapterTests(unittest.TestCase):
    def test_clean_domain(self):
        self.assertEqual(clean_domain("https://www.be-life.eu/page"), "be-life.eu")
        self.assertEqual(clean_domain("be-life.eu"), "be-life.eu")

    def test_dedupe_and_brand(self):
        self.assertEqual(dedupe_key("  Quel   Stress ? "), "quel stress ?")
        self.assertEqual(infer_brand_name("https://be-life.eu"), "Be-life")

    def test_normalize_prompts_filters_duplicates(self):
        items = [{"prompt": " quel complément stress ? ", "tags": ["Stress"]},
                 {"prompt": "quel complément stress ?", "tags": []},
                 {"prompt": "autre question", "tags": ["A", "b", "c", "d"]}]
        out = normalize_prompts(items, 10, existing={"déjà là"})
        self.assertEqual([p["prompt"] for p in out], ["quel complément stress ?", "autre question"])
        self.assertEqual(len(out[1]["tags"]), 3)


class CoverageTests(unittest.TestCase):
    def test_matrix_reports_gaps_not_invents(self):
        questions = [q("comment gérer le stress ?"), q("quel complément pour dormir ?", theme="Sommeil et endormissement")]
        cells = {(c.dimension, c.value): c for c in compute_coverage(questions, CONFIG)}
        self.assertTrue(cells[("theme", "Stress et gestion du stress")].covered)
        self.assertTrue(cells[("theme", "Sommeil et endormissement")].covered)
        self.assertFalse(cells[("competitor", "Nutergia")].covered)
        self.assertFalse(cells[("family", "comparaison_standard")].covered)

    def test_batches_only_for_gaps(self):
        questions = [q(f"question stress {i}") for i in range(6)]
        version = input_version(CONFIG, questions)
        batches = plan_batches(compute_coverage(questions, CONFIG), CONFIG, version)
        objectives = [b.objective for b in batches]
        self.assertTrue(any("Sommeil" in o for o in objectives))          # thème vide → lot
        self.assertFalse(any("Stress et gestion" in o for o in objectives))  # couvert → pas de lot
        self.assertTrue(any("Nutergia" in o for o in objectives))         # concurrent → comparai…
        self.assertTrue(all(b.input_version == version for b in batches))


class BatchExecutionTests(unittest.TestCase):
    def test_completed_batches_are_never_regenerated(self):
        batches = [Batch("b1", "obj", "theme", "x", 5)]
        calls = []
        produced = run_batches(batches, lambda o, c: calls.append(o) or {"prompts": []}, [], completed={"b1"})
        self.assertEqual(produced, [])
        self.assertEqual(calls, [])
        self.assertEqual(batches[0].status, "done")

    def test_bounded_retry_and_partial(self):
        batches = [Batch("b1", "obj", "theme", "x", 3)]
        calls = {"n": 0}
        def llm(obj, count):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("timeout")
            return {"prompts": [{"prompt": "a", "tags": []}, {"prompt": "b", "tags": []}], "model": "m"}
        produced = run_batches(batches, llm, [], completed=set())
        self.assertEqual(len(produced), 2)
        self.assertEqual(batches[0].status, "done")
        self.assertEqual(calls["n"], 2)

    def test_failed_batch_keeps_error(self):
        batches = [Batch("b1", "obj", "theme", "x", 3)]
        produced = run_batches(batches, lambda o, c: (_ for _ in ()).throw(RuntimeError("down")), [], completed=set())
        self.assertEqual(produced, [])
        self.assertEqual(batches[0].status, "failed")
        self.assertTrue(batches[0].error)

    def test_proposed_rows_keep_provenance_and_ids(self):
        items = [{"prompt": "be-life vs nutergia : lequel choisir ?", "tags": ["vs"], "batch_id": "b1", "batch_objective": "comp"}]
        rows = proposed_rows("p", items, CONFIG, "fr", {"b1": Batch("b1", "comp", "competitor", "Nutergia", 3, model="gpt-4o-mini")})
        self.assertEqual(rows[0]["provenance"], "synthetic")
        self.assertEqual(rows[0]["metadata"]["provenance_label"], "proposed")
        self.assertEqual(rows[0]["metadata"]["qualification"]["category"], "comparaison_standard")
        self.assertTrue(rows[0]["metadata"]["formulation_id"].startswith("prop:"))

    def test_resume_state_from_persisted_questions(self):
        self.assertEqual(completed_batch_ids([q("x", batch="b1"), q("y")]), {"b1", None} - {None})


if __name__ == "__main__":
    unittest.main()
