import os
import re
import base64
import time
import requests
from typing import List, Optional, Dict, Any
from datetime import datetime
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from models.raw_item import RawItem, SourceType
from utils.config_loader import Config
from sources.query_planner import plan_queries


class ForumScraper(BaseScraper):
    """Scraper pour forums (Reddit + forums génériques via Google)"""
    
    QUESTION_PATTERNS = [
        r'\?',
        r'^comment\s',
        r'^pourquoi\s',
        r'^quel(le)?s?\s',
        r'^où\s',
        r'^quand\s',
        r'^est-ce que\s',
        r'^qui\s',
        r'^combien\s',
        r'^lequel\s',
    ]
    
    DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"
    
    def __init__(self, config: Config):
        super().__init__(config)
        self.praw_client = None
        self.api_cost_usd = 0.0
        self.auth_header = self._init_dataforseo_auth()
        self._init_reddit()
    
    def _init_dataforseo_auth(self) -> Optional[str]:
        """Initialise l'authentification DataForSEO"""
        login = os.getenv("DATAFORSEO_LOGIN")
        password = os.getenv("DATAFORSEO_PASSWORD")
        
        if login and password:
            auth = base64.b64encode(f"{login}:{password}".encode()).decode()
            return f"Basic {auth}"
        return None
    
    def _init_reddit(self):
        """Reddit public JSON API - no auth needed"""
        self.reddit_headers = {
            "User-Agent": "PromptFinder/1.0 (Question scraper for GEO analysis)"
        }
        self.logger.info("Reddit public API initialized (no auth required)")
    
    @property
    def source_type(self) -> str:
        return "forum"
    
    @property
    def is_enabled(self) -> bool:
        forums_config = self.config.sources.get("forums", {})
        return forums_config.get("enabled", False)
    
    def run(self) -> List[RawItem]:
        """Exécute le scraping de tous les forums configurés"""
        if not self.is_enabled:
            self.logger.info("Forum scraper disabled")
            return []
        
        items = []
        forums_config = self.config.sources.get("forums", {})
        platforms = forums_config.get("platforms", [])
        
        for index, platform in enumerate(platforms, start=1):
            name = platform.get("name", "")
            self.logger.info(f"Scraping forum: {name}")
            self._report_progress(index - 1, len(platforms), f"Forum · {name}")
            try:
                if name == "reddit":
                    items.extend(self._scrape_reddit(platform))
                else:
                    items.extend(self._scrape_generic_forum(platform))
                self._report_progress(index, len(platforms), f"Forum · {name} · {len(items)} signaux")
            except Exception as e:
                self.logger.error(f"Error scraping {name}: {e}")
                self.errors_count += 1
                self._report_progress(index, len(platforms), f"Forum · erreur sur {name}")
        
        self.items_scraped = len(items)
        return items
    
    def _scrape_reddit(self, platform_config: dict) -> List[RawItem]:
        """Scrape Reddit via l'API JSON publique (sans authentification)"""
        items = []
        subreddits = platform_config.get("subreddits", [])
        max_threads = self.config.scraping.forum.get("max_threads", 50)
        
        for index, subreddit_name in enumerate(subreddits, start=1):
            self._report_progress(index - 1, len(subreddits), f"Reddit · r/{subreddit_name}")
            subreddit_items = self._scrape_subreddit_json(subreddit_name, max_threads)
            items.extend(subreddit_items)
            self._report_progress(index, len(subreddits), f"Reddit · r/{subreddit_name} · {len(subreddit_items)} signaux")
        
        return items
    
    def _scrape_subreddit_json(self, subreddit_name: str, max_threads: int) -> List[RawItem]:
        """Scrape un subreddit via l'API JSON publique de Reddit"""
        items = []
        
        planned_queries = plan_queries(self.config.seeds, "reddit", max_threads)
        for index, planned in enumerate(planned_queries, start=1):
            self._report_progress(index - 1, len(planned_queries), f"Reddit · r/{subreddit_name} · {planned.query}")
            try:
                url = f"https://www.reddit.com/r/{subreddit_name}/search.json"
                params = {
                    "q": planned.query,
                    "restrict_sr": "on",
                    "sort": "relevance",
                    "t": "year",
                    "limit": max(1, min(max_threads // max(len(planned_queries), 1), 25))
                }
                
                time.sleep(self.config.scraping.delay_between_requests)
                response = requests.get(url, params=params, headers=self.reddit_headers, timeout=30)
                
                if response.status_code == 429:
                    self.logger.warning(f"Reddit rate limit hit, waiting 60s...")
                    time.sleep(60)
                    response = requests.get(url, params=params, headers=self.reddit_headers, timeout=30)
                
                if response.status_code != 200:
                    self.logger.warning(f"Reddit API returned {response.status_code} for r/{subreddit_name}")
                    continue
                
                data = response.json()
                posts = data.get("data", {}).get("children", [])
                
                for post_data in posts:
                    post = post_data.get("data", {})
                    title = post.get("title", "")
                    selftext = post.get("selftext", "")
                    full_text = f"{title}\n\n{selftext}".strip()
                    
                    # Collecter tous les posts (pas seulement les questions)
                    # Le filtrage/transformation en questions se fera dans une étape ultérieure
                    if len(full_text) >= 20:  # Filtrage minimal sur la longueur
                        item = RawItem(
                            source_type=SourceType.FORUM,
                            platform="reddit",
                            raw_text=full_text,
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            title=title,
                            brand=self._detect_brand(full_text),
                            theme=self._detect_theme(full_text),
                            date=datetime.fromtimestamp(post.get("created_utc", 0)) if post.get("created_utc") else None,
                            metadata={
                                "subreddit": subreddit_name,
                                "score": post.get("score", 0),
                                "num_comments": post.get("num_comments", 0),
                                "search_term": planned.seed,
                                "seed_type": planned.seed_type,
                                "seed_priority": planned.priority,
                                "is_question": self._is_question(title) or self._is_question(selftext)
                            },
                            client_slug=self.config.client.slug
                        )
                        items.append(item)
                
                self.logger.debug(f"r/{subreddit_name} search '{planned.query}': {len(posts)} posts found")
                
            except Exception as e:
                self.logger.error(f"Error scraping r/{subreddit_name} for '{planned.query}': {e}")
            finally:
                self._report_progress(index, len(planned_queries), f"Reddit · r/{subreddit_name} · {index}/{len(planned_queries)} requêtes")
        
        self.logger.info(f"Scraped {len(items)} posts from r/{subreddit_name}")
        return items
    
    def _scrape_generic_forum(self, platform_config: dict) -> List[RawItem]:
        """Scrape un forum générique via Google site search"""
        items = []
        name = platform_config.get("name", "")
        url = platform_config.get("url", "")
        
        if not url:
            return items
        
        domain = url.replace("https://", "").replace("http://", "").split("/")[0]
        max_threads = self.config.scraping.forum.get("max_threads", 50)
        
        planned_queries = plan_queries(self.config.seeds, "forum", max_threads, domain)
        per_query_limit = max(1, min(10, max_threads // max(len(planned_queries), 1)))
        for index, planned in enumerate(planned_queries, start=1):
            self._report_progress(index - 1, len(planned_queries), f"Forum · {name} · {planned.query}")
            search_items = self._google_search_scrape(planned.query, name, per_query_limit)
            for item in search_items:
                item.metadata.update({"search_term": planned.seed, "seed_type": planned.seed_type, "seed_priority": planned.priority})
            items.extend(search_items)
            self._report_progress(index, len(planned_queries), f"Forum · {name} · {index}/{len(planned_queries)} requêtes")
        
        return items
    
    def _google_search_scrape(self, query: str, platform_name: str, limit: int) -> List[RawItem]:
        """Effectue une recherche Google via DataForSEO et scrape les résultats"""
        items = []
        
        if not self.auth_header:
            self.logger.warning("DataForSEO credentials not set, skipping Google search")
            return items
        
        try:
            payload = [{
                "keyword": query,
                "location_code": 2250,  # France
                "language_code": "fr",
                "device": "desktop",
                "os": "windows",
                "depth": min(limit, 10)
            }]
            
            url = f"{self.DATAFORSEO_BASE_URL}/serp/google/organic/live/advanced"
            headers = {
                "Authorization": self.auth_header,
                "Content-Type": "application/json"
            }
            
            time.sleep(self.config.scraping.delay_between_requests)
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            result = response.json()
            self.api_cost_usd += float(result.get("cost") or 0)
            
            if result.get("status_code") != 20000:
                self.logger.warning(f"DataForSEO search failed for '{query}'")
                return items
            
            tasks = result.get("tasks", [])
            if not tasks:
                return items
            
            task_result = tasks[0].get("result", [])
            if not task_result:
                return items
            
            serp_items = task_result[0].get("items", [])
            
            for serp_item in serp_items[:limit]:
                if serp_item.get("type") == "organic":
                    title = serp_item.get("title", "")
                    snippet = serp_item.get("description", "")
                    item_url = serp_item.get("url", "")
                    full_text = f"{title}\n\n{snippet}".strip()
                    
                    # Collecter tous les résultats (pas seulement les questions)
                    if len(full_text) >= 20:
                        item = RawItem(
                            source_type=SourceType.FORUM,
                            platform=platform_name,
                            raw_text=full_text,
                            url=item_url,
                            title=title,
                            brand=self._detect_brand(title + snippet),
                            theme=self._detect_theme(title + snippet),
                            metadata={
                                "query": query,
                                "is_question": self._is_question(title) or self._is_question(snippet)
                            },
                            client_slug=self.config.client.slug
                        )
                        items.append(item)
                
        except Exception as e:
            self.logger.error(f"Google search error: {e}")
        
        return items
    
    def _is_question(self, text: str) -> bool:
        """Détecte si le texte est une question"""
        if not text:
            return False
        
        text_lower = text.lower().strip()
        
        for pattern in self.QUESTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False
