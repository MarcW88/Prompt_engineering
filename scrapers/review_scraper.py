import re
import time
from typing import List, Optional
from datetime import datetime
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from models.raw_item import RawItem, SourceType
from utils.config_loader import Config


class ReviewScraper(BaseScraper):
    """Scraper pour avis clients (Trustpilot, Google Reviews)"""
    
    def __init__(self, config: Config):
        super().__init__(config)
    
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
        """Scrape les avis Trustpilot"""
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
