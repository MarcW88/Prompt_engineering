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
        
        for index, platform in enumerate(platforms, start=1):
            name = platform.get("name", "")
            self.logger.info(f"Scraping reviews: {name}")
            self._report_progress(index - 1, len(platforms), f"Avis · {name}")
            try:
                if name == "trustpilot":
                    items.extend(self._scrape_trustpilot(platform))
                elif name == "google_reviews":
                    items.extend(self._scrape_google_reviews(platform))
                else:
                    self.logger.warning(f"Unknown review platform: {name}")
                self._report_progress(index, len(platforms), f"Avis · {name} · {len(items)} signaux")
            except Exception as e:
                self.logger.error(f"Error scraping {name}: {e}")
                self.errors_count += 1
                self._report_progress(index, len(platforms), f"Avis · erreur sur {name}")
        
        self.items_scraped = len(items)
        return items
    
    def _scrape_trustpilot(self, platform_config: dict) -> List[RawItem]:
        """Collecte les avis Trustpilot.

        Ordre : extraction gratuite depuis les données structurées de la page
        (__NEXT_DATA__ / JSON-LD) puis DataForSEO en fallback."""
        items = self._scrape_trustpilot_nextdata(platform_config)
        if items:
            return items
        if self.auth_header:
            return self._scrape_trustpilot_dataforseo(platform_config)
        return self._scrape_trustpilot_html(platform_config)

    def _scrape_trustpilot_nextdata(self, platform_config: dict) -> List[RawItem]:
        """Extrait les avis depuis le JSON __NEXT_DATA__ embarqué dans les pages
        Trustpilot (plus robuste que les sélecteurs DOM)."""
        import json as _json

        items = []
        base_url = platform_config.get("url", "")
        if not base_url:
            return items
        max_pages = self.config.scraping.reviews.get("max_pages", 10)
        max_rating = self.config.scraping.reviews.get("max_rating", 3)
        min_length = self.config.scraping.reviews.get("min_text_length", 100)
        include_all = self.config.scraping.reviews.get("include_all_ratings", False)

        for page in range(1, max_pages + 1):
            url = f"{base_url}?page={page}" if page > 1 else base_url
            try:
                response = self._fetch(url)
                if not response:
                    break
                soup = BeautifulSoup(response.text, "lxml")
                script = soup.find("script", id="__NEXT_DATA__")
                if not script or not script.string:
                    if page == 1:
                        return items
                    break
                data = _json.loads(script.string)
                page_props = (data.get("props") or {}).get("pageProps") or {}
                reviews = page_props.get("reviews") or []
                if not reviews:
                    break
                kept_before = len(items)
                for review in reviews:
                    rating = int((review.get("rating") or review.get("stars") or 5))
                    title = review.get("title") or ""
                    text = review.get("text") or review.get("reviewText") or ""
                    raw_text = f"{title}\n\n{text}".strip() if title else text.strip()
                    if not raw_text or len(raw_text) < min_length:
                        continue
                    if not include_all and rating > max_rating:
                        continue
                    date = None
                    dates = review.get("dates") or {}
                    published = dates.get("publishedDate") or review.get("publishedDate") or review.get("createdAt")
                    if published:
                        try:
                            date = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    consumer = review.get("consumer") or {}
                    items.append(RawItem(
                        source_type=SourceType.REVIEW,
                        platform="trustpilot",
                        raw_text=raw_text,
                        url=review.get("reviewUrl") or url,
                        title=title,
                        rating=rating,
                        date=date,
                        brand=self.config.client.name,
                        metadata={
                            "author": consumer.get("displayName", "") if isinstance(consumer, dict) else "",
                            "page": page,
                            "extractor": "next_data",
                        },
                        client_slug=self.config.client.slug,
                    ))
                self.logger.info(f"Trustpilot __NEXT_DATA__ page {page}: {len(items) - kept_before} avis conservés")
            except Exception as e:
                self.logger.error(f"Trustpilot __NEXT_DATA__ error page {page}: {e}")
                break
        return items

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
        for attempt in range(60):
            if result:
                break
            if not task_id:
                return []
            self._report_progress(attempt, 60, f"Trustpilot · attente DataForSEO {attempt + 1}/60")
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
        """Google Reviews via l'instance self-hostée gosom/google-maps-scraper.

        Nécessite GOOGLE_MAPS_SCRAPER_URL (ex: http://localhost:8080).
        API : POST /api/v1/scrape -> job_id, GET /api/v1/jobs/{id} -> résultats."""
        items = []
        base_url = os.getenv("GOOGLE_MAPS_SCRAPER_URL", "").rstrip("/")
        if not base_url:
            self.logger.warning("GOOGLE_MAPS_SCRAPER_URL non défini, Google Reviews ignoré (self-hostez gosom/google-maps-scraper)")
            return items

        queries = platform_config.get("queries") or []
        if not queries:
            market = (self.config.markets or [""])[0]
            queries = [f"{self.config.client.name} {market}".strip()]
        language = (self.config.languages or ["fr"])[0]
        max_rating = self.config.scraping.reviews.get("max_rating", 3)
        min_length = self.config.scraping.reviews.get("min_text_length", 100)
        include_all = self.config.scraping.reviews.get("include_all_ratings", False)
        max_reviews = int(platform_config.get("max_reviews", 100))
        job_timeout = int(platform_config.get("timeout", 300))

        for query in queries:
            self._report_progress(0, 1, f"Google Reviews · {query}")
            try:
                response = requests.post(
                    f"{base_url}/api/v1/scrape",
                    json={
                        "keyword": query,
                        "lang": language,
                        "extra_reviews": True,
                        "max_depth": 2,
                        "timeout": min(job_timeout, 300),
                    },
                    timeout=30,
                )
                if response.status_code != 200:
                    self.logger.error(f"google-maps-scraper HTTP {response.status_code}: {response.text[:200]}")
                    continue
                job_id = response.json().get("job_id")
                if not job_id:
                    continue
                job = self._wait_maps_job(base_url, job_id, job_timeout + 60)
                if not job:
                    continue
                for place in job.get("results") or []:
                    items.extend(self._maps_place_to_items(place, query, platform_config, max_rating, min_length, include_all, max_reviews))
            except Exception as e:
                self.logger.error(f"google-maps-scraper error for '{query}': {e}")
                self.errors_count += 1
        return items

    def _wait_maps_job(self, base_url: str, job_id: str, timeout: int) -> Optional[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{base_url}/api/v1/jobs/{job_id}", timeout=30)
                if response.status_code == 200:
                    job = response.json()
                    status = job.get("status")
                    if status == "completed":
                        return job
                    if status in {"failed", "cancelled", "discarded"}:
                        self.logger.warning(f"google-maps-scraper job {job_id}: {status} {job.get('error', '')}")
                        return None
            except Exception as e:
                self.logger.debug(f"google-maps-scraper poll error: {e}")
            time.sleep(10)
        self.logger.warning(f"google-maps-scraper job {job_id} timed out")
        return None

    def _maps_place_to_items(self, place: dict, query: str, platform_config: dict,
                             max_rating: int, min_length: int,
                             include_all: bool, max_reviews: int) -> List[RawItem]:
        """Extrait les avis d'une fiche Google Maps."""
        items = []
        place_name = place.get("title") or place.get("name") or ""
        reviews = place.get("user_reviews") or place.get("reviews") or []
        if isinstance(reviews, dict):
            reviews = reviews.get("reviews") or reviews.get("items") or []
        for review in reviews[:max_reviews]:
            if not isinstance(review, dict):
                continue
            text = str(review.get("description") or review.get("text") or review.get("review") or "").strip()
            if len(text) < min_length:
                continue
            try:
                rating = int(float(review.get("rating") or 5))
            except (TypeError, ValueError):
                rating = 5
            if not include_all and rating > max_rating:
                continue
            date = None
            when = review.get("when") or review.get("date") or review.get("published_at")
            if when and not isinstance(when, str):
                when = str(when)
            items.append(RawItem(
                source_type=SourceType.REVIEW,
                platform="google_reviews",
                raw_text=text,
                url=place.get("link") or place.get("url") or "",
                title=f"{place_name} · {rating}★".strip(),
                rating=rating,
                brand=self.config.client.name,
                metadata={
                    "query": query,
                    "place": place_name,
                    "author": str(review.get("name") or review.get("author") or ""),
                    "when": when or "",
                    "extractor": "google_maps_scraper",
                },
                client_slug=self.config.client.slug,
            ))
        return items
