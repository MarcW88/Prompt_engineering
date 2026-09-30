import tempfile
import unittest
from pathlib import Path

from models.seed import Seed, SeedType, deduplicate_seeds
from sources.query_planner import expand_serp_templates, plan_queries
from utils.config_loader import load_config


class SeedTests(unittest.TestCase):
    def test_deduplicates_by_type_and_keeps_highest_priority(self):
        seeds = deduplicate_seeds([
            Seed("Trail", SeedType.KEYWORD, 20),
            Seed("trail", SeedType.KEYWORD, 90),
            Seed("trail", SeedType.THEME, 50),
        ])
        self.assertEqual(len(seeds), 2)
        self.assertEqual(seeds[0].priority, 90)

    def test_plans_reddit_queries_by_priority_and_budget(self):
        seeds = [
            Seed("low", SeedType.KEYWORD, 10),
            Seed("high", SeedType.PROBLEM, 100),
            Seed("disabled", SeedType.KEYWORD, 100, enabled=False),
        ]
        planned = plan_queries(seeds, "reddit", 1)
        self.assertEqual([query.query for query in planned], ["high"])

    def test_plans_forum_site_queries(self):
        planned = plan_queries([Seed("chaussures trail", SeedType.KEYWORD, 80)], "forum", 5, "forum.example")
        self.assertEqual(planned[0].query, "site:forum.example chaussures trail")

    def test_expands_serp_templates(self):
        seeds = [
            Seed("chaussures trail", SeedType.KEYWORD, 90),
            Seed("Decathlon", SeedType.BRAND, 80),
            Seed("Intersport", SeedType.COMPETITOR, 70),
        ]
        planned = expand_serp_templates(seeds, ["{seed}", "{seed} {brand_variant}", "{seed} vs {competitor}"], 10)
        queries = [query.query for query in planned]
        self.assertIn("chaussures trail", queries)
        self.assertIn("chaussures trail Decathlon", queries)
        self.assertIn("chaussures trail vs Intersport", queries)

    def test_config_merges_explicit_and_legacy_seeds(self):
        yaml = """
client:
  name: Demo
  slug: demo
brand_variants: [Demo]
markets: [BE]
languages: [fr]
themes: [trail]
competitors: [Rival]
seeds:
  - value: chaussures trail débutant
    type: keyword
    priority: 100
sources: {}
scraping: {}
filters: {}
output: {}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml)
            config = load_config(str(path))
        self.assertEqual(len(config.seeds), 4)
        self.assertEqual(config.seeds[0].value, "chaussures trail débutant")


if __name__ == "__main__":
    unittest.main()
