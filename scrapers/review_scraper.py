import base64
import os
import re
import time
from typing import List, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import requests

from .base_scraper import BaseScraper
from models.raw_item import RawItem, SourceType
from utils.config_loader import Config


class ReviewScraper(BaseScraper):
    """Scraper pour avis clients (Trustpilot, Google Reviews)"""
    
    def __init__(self, config: Config):
        super().__init__(config)
        self.api_cost_usd = 0.0
        self.auth_header = self._init_dataforseo_auth()

    def _init_dataforseo_auth(self) -> Optional[str]:
        login = os.getenv("DATAFORSEO_LOGIN")
        password = os.getenv("DATAFORSEO_PASSWORD")
        if login and password:
            auth = base64.b64encode(f"{login}:{password}".encode()).decode()
            return f"Basic {auth}"
        return None
    
    @property
    def source_type(self) -> str:
        return "review"
    
    @property
    def is_enabled(self) -> bool:
        reviews_config = self.config.sources.get("reviews", {})
        return reviews_config.get("enabled", False)
    
    def run(self) -> List[RawItem]:
        """Exécute le scraping de toutes les plateformes d'avis"""
        if not self.is_enabled:
            self.logger.info("Review scraper disabled")
            return []
        
        items = []
        reviews_config = self.config.sources.get("reviews", {})
        platforms = reviews_config.get("platforms", [])
        
        for platform in platforms:
            name = platform.get("name", "")
            self.logger.info(f"Scraping reviews: {name}")
            
            try:
                if name == "trustpilot":
                    items.extend(self._scrape_trustpilot(platform))
                elif name == "google_reviews":
                    items.extend(self._scrape_google_reviews(platform))
                else:
                    self.logger.warning(f"Unknown review platform: {name}")
            except Exception as e:
                self.logger.error(f"Error scraping {name}: {e}")
                self.errors_count += 1
        
        self.items_scraped = len(items)
        return items
    
    def _scrape_trustpilot(self, platform_config: dict) -> List[RawItem]:
        """Collecte les avis Trustpilot via DataForSEO, avec fallback HTML."""
        if self.auth_header:
            return self._scrape_trustpilot_dataforseo(platform_config)
        return self._scrape_trustpilot_html(platform_config)

    def _trustpilot_domain(self, platform_config: dict) -> str:
        configured = platform_config.get("domain", "")
        if configured:
            return configured
        match = re.search(r"/review/([^/?#]+)", platform_config.get("url", ""))
        return match.group(1) if match else ""

    def _response_cost(self, data: dict) -> float:
        task_cost = sum(float(task.get("cost") or 0) for task in data.get("tasks", []))
        return float(data.get("cost") or task_cost)

    def _scrape_trustpilot_dataforseo(self, platform_config: dict) -> List[RawItem]:
        domain = self._trustpilot_domain(platform_config)
        if not domain:
            self.logger.warning("No Trustpilot domain configured")
            return []
        max_pages = int(self.config.scraping.reviews.get("max_pages", 10))
        depth = min(100, max(20, max_pages * 20))
        headers = {"Authorization": self.auth_header, "Content-Type": "application/json"}
        response = requests.post(
            "https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
            headers=headers, json=[{"domain": domain, "depth": depth, "sort_by": "recency"}], timeout=60
        )
        response.raise_for_status()
        data = response.json()
        self.api_cost_usd += self._response_cost(data)
        task = (data.get("tasks") or [{}])[0]
        if task.get("status_code") not in {20000, 20100}:
            self.logger.warning(f"DataForSEO Trustpilot task failed: {task.get('status_message')}")
            return []
        result = task.get("result") or []
        task_id = task.get("id")
        for _ in range(60):
            if result:
                break
            if not task_id:
                return []
            time.sleep(5)
            response = requests.get(f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{task_id}", headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            task = (data.get("tasks") or [{}])[0]
            result = task.get("result") or []
            if not result and task.get("status_code") not in {20100, 40602}:
                self.logger.warning(f"DataForSEO Trustpilot task failed: {task.get('status_message')}")
                return []
        reviews = (result[0].get("items") if result else []) or []
        max_rating = self.config.scraping.reviews.get("max_rating", 3)
        min_length = self.config.scraping.reviews.get("min_text_length", 100)
        include_all = self.config.scraping.reviews.get("include_all_ratings", False)
        items = []
        for review in reviews:
            rating = int((review.get("rating") or {}).get("value") or 5)
            title = review.get("title", "")
            text = review.get("review_text", "")
            raw_text = f"{title}\n\n{text}" if title else text
            if (include_all or rating <= max_rating) and len(raw_text) >= min_length:
                timestamp = review.get("timestamp")
                date = None
                if timestamp:
                    try:
                        date = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %z")
                    except ValueError:
                        pass
                items.append(RawItem(
                    source_type=SourceType.REVIEW, platform="trustpilot", raw_text=raw_text,
                    url=review.get("url", platform_config.get("url", "")), title=title,
                    rating=rating, date=date, brand=self.config.client.name,
                    metadata={"author": (review.get("user_profile") or {}).get("name", ""), "verified": review.get("verified"), "language": review.get("language"), "provider": "dataforseo"},
                    client_slug=self.config.client.slug
                ))
        return items

    def _scrape_trustpilot_html(self, platform_config: dict) -> List[RawItem]:
        """Fallback HTML pour environnements sans credentials DataForSEO."""
        items = []
        base_url = platform_config.get("url", "")
        
        if not base_url:
            self.logger.warning("No Trustpilot URL configured")
            return items
        
        max_pages = self.config.scraping.reviews.get("max_pages", 10)
        max_rating = self.config.scraping.reviews.get("max_rating", 3)
        min_length = self.config.scraping.reviews.get("min_text_length", 100)
        include_all = self.config.scraping.reviews.get("include_all_ratings", False)
        
        for page in range(1, max_pages + 1):
            url = f"{base_url}?page={page}"
            
            try:
                response = self._fetch(url)
                if not response:
                    break
                
                soup = BeautifulSoup(response.text, "lxml")
                reviews = self._parse_trustpilot_page(soup)
                
                if not reviews:
                    self.logger.info(f"No more reviews at page {page}")
                    break
                
                for review in reviews:
                    rating = review.get("rating", 5)
                    text = review.get("text", "")
                    
                    if include_all or rating <= max_rating:
                        if len(text) >= min_length:
                            item = RawItem(
                                source_type=SourceType.REVIEW,
                                platform="trustpilot",
                                raw_text=text,
                                url=review.get("url", url),
                                title=review.get("title", ""),
                                rating=rating,
                                date=review.get("date"),
                                brand=self.config.client.name,
                                metadata={
                                    "author": review.get("author", ""),
                                    "page": page
                                },
                                client_slug=self.config.client.slug
                            )
                            items.append(item)
                
                self.logger.info(f"Page {page}: {len(reviews)} reviews found, {len(items)} total kept")
                
            except Exception as e:
                self.logger.error(f"Error on page {page}: {e}")
                break
        
        return items
    
    def _parse_trustpilot_page(self, soup: BeautifulSoup) -> List[dict]:
        """Parse une page Trustpilot et extrait les avis"""
        reviews = []
        
        review_cards = soup.select('article[data-service-review-card-paper="true"]')
        
        if not review_cards:
            review_cards = soup.select('div.review-card, article.review')
        
        for card in review_cards:
            try:
                title_elem = card.select_one('h2, [data-service-review-title-typography="true"]')
                title = title_elem.get_text(strip=True) if title_elem else ""
                
                text_elem = card.select_one('p[data-service-review-text-typography="true"], .review-content__text')
                text = text_elem.get_text(strip=True) if text_elem else ""
                
                rating = 3
                rating_elem = card.select_one('div[data-service-review-rating]')
                if rating_elem:
                    rating_attr = rating_elem.get('data-service-review-rating', '3')
                    try:
                        rating = int(rating_attr)
                    except ValueError:
                        pass
                else:
                    stars = card.select('img[alt*="star"], .star-rating')
                    if stars:
                        rating = len([s for s in stars if 'full' in str(s).lower() or 'filled' in str(s).lower()])
                
                author_elem = card.select_one('[data-consumer-name-typography="true"], .consumer-information__name')
                author = author_elem.get_text(strip=True) if author_elem else ""
                
                date_elem = card.select_one('time, [data-service-review-date-time-ago="true"]')
                date = None
                if date_elem:
                    date_str = date_elem.get('datetime', '')
                    if date_str:
                        try:
                            date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        except ValueError:
                            pass
                
                if text:
                    reviews.append({
                        "title": title,
                        "text": f"{title}\n\n{text}" if title else text,
                        "rating": rating,
                        "author": author,
                        "date": date
                    })
                    
            except Exception as e:
                self.logger.debug(f"Error parsing review card: {e}")
                continue
        
        return reviews
    
    def _scrape_google_reviews(self, platform_config: dict) -> List[RawItem]:
        """Scrape Google Reviews (nécessite Places API ou scraping avancé)"""
        items = []
        
        self.logger.warning("Google Reviews scraping requires Places API - not implemented in basic version")
        self.logger.info("Consider using SERPAPI with 'google_maps_reviews' endpoint")
        
        return items
