import os
import base64
import time
import requests
from typing import List, Set, Optional, Dict, Any
from datetime import datetime

from .base_scraper import BaseScraper
from models.raw_item import RawItem, SourceType
from utils.config_loader import Config
from sources.query_planner import expand_serp_templates


class SerpScraper(BaseScraper):
    """Scraper pour SERP via DataForSEO (PAA, suggestions, questions)"""
    
    DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"
    
    def __init__(self, config: Config):
        super().__init__(config)
        self.seen_questions: Set[str] = set()
        self.api_cost_usd = 0.0
        self.auth_header = self._init_auth()
    
    def _init_auth(self) -> Optional[str]:
        """Initialise l'authentification DataForSEO"""
        login = os.getenv("DATAFORSEO_LOGIN")
        password = os.getenv("DATAFORSEO_PASSWORD")
        
        if login and password:
            auth = base64.b64encode(f"{login}:{password}".encode()).decode()
            self.logger.info("DataForSEO authentication initialized")
            return f"Basic {auth}"
        return None
    
    def _dataforseo_request(self, endpoint: str, payload: List[Dict]) -> Optional[Dict]:
        """Effectue une requête à l'API DataForSEO"""
        if not self.auth_header:
            return None
        
        url = f"{self.DATAFORSEO_BASE_URL}/{endpoint}"
        headers = {
            "Authorization": self.auth_header,
            "Content-Type": "application/json"
        }
        
        try:
            time.sleep(self.config.scraping.delay_between_requests)
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            result = response.json()
            self.api_cost_usd += float(result.get("cost") or 0)
            return result
        except Exception as e:
            self.logger.error(f"DataForSEO request error: {e}")
            return None
    
    @property
    def source_type(self) -> str:
        return "serp"
    
    @property
    def is_enabled(self) -> bool:
        serp_config = self.config.sources.get("serp", {})
        return serp_config.get("enabled", False)
    
    def run(self) -> List[RawItem]:
        """Exécute le scraping SERP via DataForSEO"""
        if not self.is_enabled:
            self.logger.info("SERP scraper disabled")
            return []
        
        if not self.auth_header:
            self.logger.warning("DataForSEO credentials not set, SERP scraping disabled")
            return []
        
        items = []
        serp_config = self.config.sources.get("serp", {})
        query_templates = serp_config.get("query_templates", [])
        
        queries = self._generate_queries(query_templates)
        self.logger.info(f"Generated {len(queries)} search queries")
        
        for planned in queries:
            try:
                query_items = [*self._scrape_paa_dataforseo(planned.query), *self._scrape_suggestions_dataforseo(planned.query)]
                for item in query_items:
                    item.metadata.update({"search_term": planned.seed, "seed_type": planned.seed_type, "seed_priority": planned.priority})
                items.extend(query_items)
                
            except Exception as e:
                self.logger.error(f"Error scraping SERP for '{planned.query}': {e}")
                self.errors_count += 1
        
        self.items_scraped = len(items)
        return items
    
    def _generate_queries(self, templates: List[str]):
        """Génère les requêtes à partir des seeds prioritaires et des templates"""
        budget = int(self.config.scraping.serp.get("query_budget", 50))
        return expand_serp_templates(self.config.seeds, templates, budget)
    
    def _scrape_paa_dataforseo(self, query: str) -> List[RawItem]:
        """Scrape les People Also Ask via DataForSEO"""
        items = []
        max_depth = self.config.scraping.serp.get("max_paa_depth", 3)
        
        payload = [{
            "keyword": query,
            "location_code": 2250,  # France
            "language_code": "fr",
            "device": "desktop",
            "os": "windows"
        }]
        
        result = self._dataforseo_request("serp/google/organic/live/advanced", payload)
        
        if not result or result.get("status_code") != 20000:
            self.logger.warning(f"DataForSEO PAA request failed for '{query}'")
            return items
        
        try:
            tasks = result.get("tasks", [])
            if not tasks:
                return items
            
            task_result = tasks[0].get("result", [])
            if not task_result:
                return items
            
            serp_items = task_result[0].get("items", [])
            
            for serp_item in serp_items:
                if not isinstance(serp_item, dict):
                    continue
                    
                item_type = serp_item.get("type", "")
                
                if item_type == "people_also_ask":
                    paa_items_data = serp_item.get("items", [])
                    if not isinstance(paa_items_data, list):
                        continue
                    
                    for i, paa in enumerate(paa_items_data[:max_depth]):
                        if not isinstance(paa, dict):
                            continue
                        q_text = paa.get("title", "")
                        
                        if q_text and q_text.lower() not in self.seen_questions:
                            self.seen_questions.add(q_text.lower())
                            
                            snippet = ""
                            expanded = paa.get("expanded_element")
                            if isinstance(expanded, list) and expanded:
                                first_exp = expanded[0]
                                if isinstance(first_exp, dict):
                                    snippet = first_exp.get("description", "")
                            
                            source_url = paa.get("url", "") if isinstance(paa.get("url"), str) else ""
                            
                            item = RawItem(
                                source_type=SourceType.SERP,
                                platform="google_paa",
                                raw_text=q_text,
                                url=source_url or f"https://google.fr/search?q={query}",
                                title=q_text,
                                brand=self._detect_brand(q_text),
                                theme=self._detect_theme(q_text),
                                metadata={
                                    "query": query,
                                    "snippet": snippet,
                                    "position": i + 1,
                                    "type": "paa"
                                },
                                client_slug=self.config.client.slug
                            )
                            items.append(item)
                
                elif item_type == "related_searches":
                    related = serp_item.get("items", [])
                    if not isinstance(related, list):
                        continue
                    for rel in related[:5]:
                        if not isinstance(rel, dict):
                            continue
                        rel_text = rel.get("title", "")
                        if rel_text and "?" in rel_text and rel_text.lower() not in self.seen_questions:
                            self.seen_questions.add(rel_text.lower())
                            item = RawItem(
                                source_type=SourceType.SERP,
                                platform="google_related",
                                raw_text=rel_text,
                                url=f"https://google.fr/search?q={rel_text}",
                                title=rel_text,
                                brand=self._detect_brand(rel_text),
                                theme=self._detect_theme(rel_text),
                                metadata={"query": query, "type": "related"},
                                client_slug=self.config.client.slug
                            )
                            items.append(item)
            
            self.logger.debug(f"Query '{query}': {len(items)} PAA/related questions")
            
        except Exception as e:
            self.logger.error(f"PAA parsing error: {e}")
        
        return items
    
    def _scrape_suggestions_dataforseo(self, query: str) -> List[RawItem]:
        """Scrape les suggestions Google Autocomplete via DataForSEO"""
        items = []
        max_suggestions = self.config.scraping.serp.get("max_suggestions", 10)
        
        payload = [{
            "keyword": query,
            "location_code": 2250,  # France
            "language_code": "fr"
        }]
        
        result = self._dataforseo_request("serp/google/autocomplete/live", payload)
        
        if not result or result.get("status_code") != 20000:
            self.logger.debug(f"DataForSEO suggestions request failed for '{query}'")
            return items
        
        try:
            tasks = result.get("tasks", [])
            if not tasks:
                return items
            
            task_result = tasks[0].get("result", [])
            if not task_result:
                return items
            
            suggestions = task_result[0].get("items", [])
            
            for i, suggestion in enumerate(suggestions[:max_suggestions]):
                s_text = suggestion.get("title", "") or suggestion.get("suggestion", "")
                
                if s_text and s_text.lower() not in self.seen_questions:
                    if "?" in s_text or any(kw in s_text.lower() for kw in ["comment", "pourquoi", "quel", "où", "quand", "combien"]):
                        self.seen_questions.add(s_text.lower())
                        
                        item = RawItem(
                            source_type=SourceType.SERP,
                            platform="google_suggest",
                            raw_text=s_text,
                            url=f"https://google.fr/search?q={s_text}",
                            title=s_text,
                            brand=self._detect_brand(s_text),
                            theme=self._detect_theme(s_text),
                            metadata={
                                "original_query": query,
                                "position": i + 1,
                                "type": "suggestion"
                            },
                            client_slug=self.config.client.slug
                        )
                        items.append(item)
            
        except Exception as e:
            self.logger.error(f"Suggestions parsing error: {e}")
        
        return items
