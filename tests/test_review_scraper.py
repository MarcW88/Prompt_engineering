import os
import unittest
from unittest.mock import Mock, patch

from scrapers import ReviewScraper
from utils.config_loader import load_config


class ReviewScraperTests(unittest.TestCase):
    @patch("scrapers.review_scraper.time.sleep", return_value=None)
    @patch("scrapers.review_scraper.requests.get")
    @patch("scrapers.review_scraper.requests.post")
    def test_collects_trustpilot_reviews_from_dataforseo(self, post, get, _sleep):
        post_response = Mock()
        post_response.json.return_value = {"cost": 0.00075, "tasks": [{"id": "task-1", "status_code": 20100, "result": []}]}
        post_response.raise_for_status.return_value = None
        get_response = Mock()
        get_response.json.return_value = {"tasks": [{"id": "task-1", "status_code": 20000, "result": [{"items": [{
            "url": "https://fr.trustpilot.com/reviews/1",
            "title": "Problème de livraison",
            "review_text": "La livraison a pris deux semaines et le service client ne répondait pas.",
            "rating": {"value": 1},
            "timestamp": "2026-10-01 12:00:00 +00:00",
            "verified": True,
            "language": "fr",
            "user_profile": {"name": "Marc"},
        }]}]}]}
        get_response.raise_for_status.return_value = None
        post.return_value = post_response
        get.return_value = get_response
        with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "login", "DATAFORSEO_PASSWORD": "password"}):
            config = load_config("config/decathlon.yaml")
            config.scraping.reviews["max_pages"] = 1
            config.scraping.reviews["min_text_length"] = 10
            scraper = ReviewScraper(config)
            items = scraper._scrape_trustpilot({"url": "https://fr.trustpilot.com/review/www.decathlon.fr"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].platform, "trustpilot")
        self.assertEqual(items[0].rating, 1)
        self.assertEqual(items[0].metadata["provider"], "dataforseo")
        self.assertEqual(scraper.api_cost_usd, 0.00075)


if __name__ == "__main__":
    unittest.main()
