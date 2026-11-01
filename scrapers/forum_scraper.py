import os
import re
import base64
import time
import requests
from typing import List, Optional, Dict, Any
from datetime import datetime
from bs4 import BeautifulSoup

from .arctic_shift import ArcticShiftClient
from .base_scraper import BaseScraper
from .extractors import extract_url_content
from models.raw_item import RawItem, SourceType
from utils.config_loader import Config
from sources.discovery import SourceDiscovery
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
        self.discovery = SourceDiscovery(
            delay=self.config.scraping.delay_between_requests,
            timeout=self.config.scraping.timeout,
            logger=self.logger,
        )
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
        self.arctic = ArcticShiftClient(
            delay=self.config.scraping.delay_between_requests,
            timeout=self.config.scraping.timeout,
            logger=self.logger,
        )
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
            subreddit_items = self._scrape_subreddit(subreddit_name, max_threads)
            items.extend(subreddit_items)
            self._report_progress(index, len(subreddits), f"Reddit · r/{subreddit_name} · {len(subreddit_items)} signaux")
        
        return items
    
    def _scrape_subreddit(self, subreddit_name: str, max_threads: int) -> List[RawItem]:
        """Scrape un subreddit : Arctic Shift d'abord, API JSON Reddit en fallback."""
        items = self._scrape_subreddit_arctic(subreddit_name, max_threads)
        if items:
            return items
        self.logger.info(f"Arctic Shift returned nothing for r/{subreddit_name}, falling back to Reddit JSON API")
        return self._scrape_subreddit_json(subreddit_name, max_threads)

    def _scrape_subreddit_arctic(self, subreddit_name: str, max_threads: int) -> List[RawItem]:
        """Scrape un subreddit via Arctic Shift (archive Reddit, pas de clé requise).

        Récupère les posts correspondant aux seeds ainsi que les commentaires
        des threads les plus pertinents, qui contiennent souvent les vraies
        formulations utilisateurs."""
        items = []
        max_comments = int(self.config.scraping.forum.get("max_replies_per_thread", 3))
        comment_thread_limit = int(self.config.scraping.forum.get("arctic_comment_threads", 5))

        planned_queries = plan_queries(self.config.seeds, "reddit", max_threads)
        per_query_limit = max(1, min(max_threads // max(len(planned_queries), 1), 100))
        commented = 0
        for index, planned in enumerate(planned_queries, start=1):
            self._report_progress(index - 1, len(planned_queries), f"Reddit · r/{subreddit_name} · {planned.query}")
            try:
                posts = self.arctic.search_posts(subreddit_name, planned.query, limit=per_query_limit,
                    after=self.config.scraping.forum.get("after", ""), before=self.config.scraping.forum.get("before", ""))
                for post in posts:
                    title = post.get("title", "") or ""
                    selftext = post.get("selftext", "") or ""
                    full_text = f"{title}\n\n{selftext}".strip()
                    if len(full_text) < 20:
                        continue
                    created = post.get("created_utc")
                    try:
                        date = datetime.fromtimestamp(int(created)) if created else None
                    except (TypeError, ValueError):
                        date = None
                    items.append(RawItem(
                        source_type=SourceType.FORUM,
                        platform="reddit",
                        raw_text=full_text,
                        url=f"https://reddit.com{post.get('permalink', '')}",
                        title=title,
                        brand=self._detect_brand(full_text),
                        theme=self._detect_theme(full_text),
                        date=date,
                        metadata={
                            "subreddit": subreddit_name,
                            "provider": "arctic_shift",
                            "signal_kind": "post",
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "search_term": planned.seed,
                            "seed_type": planned.seed_type,
                            "seed_priority": planned.priority,
                            "is_question": self._is_question(title) or self._is_question(selftext),
                        },
                        client_slug=self.config.client.slug,
                    ))
                    if commented < comment_thread_limit and post.get("id"):
                        comments = self.arctic._get("comments/search", {
                            "link_id": post["id"], "limit": max_comments
                        })
                        commented += 1 if comments else 0
                        for comment in comments:
                            body = (comment.get("body") or "").strip()
                            if len(body) < 20:
                                continue
                            c_created = comment.get("created_utc")
                            try:
                                c_date = datetime.fromtimestamp(int(c_created)) if c_created else None
                            except (TypeError, ValueError):
                                c_date = None
                            items.append(RawItem(
                                source_type=SourceType.FORUM,
                                platform="reddit",
                                raw_text=body,
                                url=f"https://reddit.com{comment.get('permalink', '') or post.get('permalink', '')}",
                                title=f"Commentaire · {title[:80]}",
                                brand=self._detect_brand(body),
                                theme=self._detect_theme(body),
                                date=c_date,
                                metadata={
                                    "subreddit": subreddit_name,
                                    "provider": "arctic_shift",
                                    "signal_kind": "comment",
                                    "post_id": post.get("id"),
                                    "search_term": planned.seed,
                                    "seed_type": planned.seed_type,
                                    "seed_priority": planned.priority,
                                    "is_question": self._is_question(body),
                                },
                                client_slug=self.config.client.slug,
                            ))
            except Exception as e:
                self.logger.error(f"Arctic Shift error on r/{subreddit_name} for '{planned.query}': {e}")
            finally:
                self._report_progress(index, len(planned_queries), f"Reddit · r/{subreddit_name} · {index}/{len(planned_queries)} requêtes")
            if self.arctic.available is False:
                break

        self.logger.info(f"Arctic Shift: {len(items)} items from r/{subreddit_name}")
        return items

    def _scrape_subreddit_json(self, subreddit_name: str, max_threads: int) -> List[RawItem]:
        """Scrape un subreddit via l'API JSON publique de Reddit"""
        items = []
        max_comments = int(self.config.scraping.forum.get("max_replies_per_thread", 3))
        comment_thread_limit = int(self.config.scraping.forum.get("arctic_comment_threads", 5))
        commented = 0

        planned_queries = plan_queries(self.config.seeds, "reddit", max_threads)
        for index, planned in enumerate(planned_queries, start=1):
            self._report_progress(index - 1, len(planned_queries), f"Reddit · r/{subreddit_name} · {planned.query}")
            try:
                url = f"https://www.reddit.com/r/{subreddit_name}/search.json"
                params = {
                    "q": planned.query,
                    "restrict_sr": "on",
                    "sort": "relevance",
                    "t": self.config.scraping.forum.get("time_filter", "year"),
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
                                "provider": "reddit_public_json",
                                "signal_kind": "post",
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
                        # Fallback commentaires via le JSON public du thread.
                        if commented < comment_thread_limit and post.get("num_comments", 0) > 0 and post.get("permalink"):
                            try:
                                time.sleep(self.config.scraping.delay_between_requests)
                                c_response = requests.get(f"https://www.reddit.com{post['permalink']}.json",
                                    params={"limit": max_comments, "depth": 1},
                                    headers=self.reddit_headers, timeout=30)
                                if c_response.status_code == 200:
                                    listing = c_response.json()
                                    children = (listing[1] if isinstance(listing, list) and len(listing) > 1 else {}).get("data", {}).get("children", [])
                                    fetched = 0
                                    for child in children:
                                        if fetched >= max_comments or child.get("kind") != "t1":
                                            break
                                        body = (child.get("data", {}).get("body") or "").strip()
                                        if len(body) < 20:
                                            continue
                                        fetched += 1
                                        c_created = child["data"].get("created_utc")
                                        items.append(RawItem(
                                            source_type=SourceType.FORUM,
                                            platform="reddit",
                                            raw_text=body,
                                            url=f"https://reddit.com{child['data'].get('permalink', '') or post.get('permalink', '')}",
                                            title=f"Commentaire · {title[:80]}",
                                            brand=self._detect_brand(body),
                                            theme=self._detect_theme(body),
                                            date=datetime.fromtimestamp(c_created) if c_created else None,
                                            metadata={
                                                "subreddit": subreddit_name,
                                                "provider": "reddit_public_json",
                                                "signal_kind": "comment",
                                                "post_id": post.get("id"),
                                                "search_term": planned.seed,
                                                "seed_type": planned.seed_type,
                                                "seed_priority": planned.priority,
                                                "is_question": self._is_question(body),
                                            },
                                            client_slug=self.config.client.slug,
                                        ))
                                    commented += 1 if fetched else 0
                            except Exception as error:
                                self.logger.debug(f"Reddit comments fetch failed for {post.get('permalink')}: {error}")

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
            search_items = self._discover_and_extract(planned.query, name, per_query_limit)
            for item in search_items:
                item.metadata.update({"search_term": planned.seed, "seed_type": planned.seed_type, "seed_priority": planned.priority})
            items.extend(search_items)
            self._report_progress(index, len(planned_queries), f"Forum · {name} · {index}/{len(planned_queries)} requêtes")

        self.api_cost_usd += self.discovery.api_cost_usd
        return items

    def _discover_and_extract(self, query: str, platform_name: str, limit: int) -> List[RawItem]:
        """Découvre des URLs via SearXNG (ou DataForSEO) puis extrait le contenu
        réel de la page via forumscraper / trafilatura.

        Si l'extraction échoue, le snippet de recherche est conservé comme
        signal minimal."""
        items = []
        language = (self.config.languages or ["fr"])[0]
        country = (self.config.markets or ["FR"])[0]

        try:
            results = self.discovery.search(query, limit=limit, language=language, country=country)
        except Exception as e:
            self.logger.error(f"Source discovery error for '{query}': {e}")
            return items

        for result in results:
            item_url = result.get("url", "")
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            if not item_url:
                continue

            extracted = extract_url_content(
                item_url, session=self.session,
                timeout=self.config.scraping.timeout, logger=self.logger,
            )
            if extracted and extracted.get("posts"):
                # Thread de forum structuré : un item par post.
                thread_title = extracted.get("title") or title
                for post in extracted["posts"]:
                    items.append(RawItem(
                        source_type=SourceType.FORUM,
                        platform=platform_name,
                        raw_text=post["text"],
                        url=item_url,
                        title=thread_title,
                        brand=self._detect_brand(post["text"]),
                        theme=self._detect_theme(post["text"]),
                        metadata={
                            "query": query,
                            "extractor": extracted.get("engine", "forumscraper"),
                            "signal_kind": "forum_post",
                            "author": post.get("author", ""),
                            "is_question": self._is_question(post["text"]),
                        },
                        client_slug=self.config.client.slug,
                    ))
            elif extracted and extracted.get("text"):
                full_text = extracted["text"]
                items.append(RawItem(
                    source_type=SourceType.FORUM,
                    platform=platform_name,
                    raw_text=full_text[:8000],
                    url=item_url,
                    title=extracted.get("title") or title,
                    brand=self._detect_brand(full_text),
                    theme=self._detect_theme(full_text),
                    metadata={
                        "query": query,
                        "extractor": extracted.get("engine", "trafilatura"),
                        "signal_kind": "page_content",
                        "is_question": self._is_question(title) or self._is_question(full_text[:500]),
                    },
                    client_slug=self.config.client.slug,
                ))
            else:
                full_text = f"{title}\n\n{snippet}".strip()
                if len(full_text) >= 20:
                    items.append(RawItem(
                        source_type=SourceType.FORUM,
                        platform=platform_name,
                        raw_text=full_text,
                        url=item_url,
                        title=title,
                        brand=self._detect_brand(full_text),
                        theme=self._detect_theme(full_text),
                        metadata={
                            "query": query,
                            "extractor": "serp_snippet",
                            "is_question": self._is_question(title) or self._is_question(snippet),
                        },
                        client_slug=self.config.client.slug,
                    ))

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
