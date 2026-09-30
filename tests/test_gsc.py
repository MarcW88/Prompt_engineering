import tempfile
import unittest
from pathlib import Path

from sources.gsc import parse_gsc_content
from storage.raw_storage import RawStorage


class GscParserTests(unittest.TestCase):
    def test_parses_conversational_queries_and_metrics(self):
        content = (
            "Top queries,Clicks,Impressions\n"
            "quelle est la meilleure chaussure de trail pour commencer sur terrain humide,12,340\n"
            "chaussure trail,20,500\n"
        ).encode()
        items = parse_gsc_content(content, min_words=10, client_slug="demo")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metadata["clicks"], 12)
        self.assertEqual(items[0].metadata["impressions"], 340)
        self.assertEqual(items[0].source_type.value, "gsc_conversation")

    def test_supports_semicolon_and_deduplicates(self):
        query = "comment choisir une tente légère pour une randonnée de plusieurs jours en montagne"
        content = f"Requête;Clics;Impressions\n{query};2;40\n{query};2;40\n".encode()
        self.assertEqual(len(parse_gsc_content(content, min_words=8)), 1)

    def test_storage_keeps_distinct_queries_from_same_source(self):
        content = (
            "Query,Clicks,Impressions\n"
            "comment choisir une tente légère pour une randonnée de plusieurs jours,2,40\n"
            "quelles chaussures choisir pour débuter le trail sur un terrain humide,3,60\n"
        ).encode()
        items = parse_gsc_content(content, min_words=8, client_slug="demo")
        with tempfile.TemporaryDirectory() as directory:
            storage = RawStorage(str(Path(directory) / "raw.db"))
            self.assertEqual(storage.save(items), 2)
            self.assertEqual(storage.save(items), 0)
            self.assertEqual(len(storage.get_all()), 2)


if __name__ == "__main__":
    unittest.main()
