from abc import ABC, abstractmethod
from typing import List, Optional
import time
import backoff
import requests
from requests.exceptions import RequestException

from models.raw_item import RawItem
from utils.config_loader import Config
from utils.logger import get_logger


class BaseScraper(ABC):
    """Interface de base pour tous les scrapers"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        self.session = self._create_session()
        self.items_scraped = 0
        self.errors_count = 0
        self.progress_callback = None

    def _report_progress(self, processed: int, total: int, detail: str = ""):
        if callable(self.progress_callback):
            self.progress_callback(processed, total, detail)
    
    def _create_session(self) -> requests.Session:
        """Crée une session HTTP avec headers par défaut"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        })
        return session
    
    @backoff.on_exception(
        backoff.expo,
        RequestException,
        max_tries=3,
        max_time=60
    )
    def _fetch(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Fetch une URL avec retry et rate limiting"""
        time.sleep(self.config.scraping.delay_between_requests)
        
        try:
            response = self.session.get(
                url,
                timeout=self.config.scraping.timeout,
                **kwargs
            )
            response.raise_for_status()
            return response
        except RequestException as e:
            self.logger.error(f"Fetch error for {url}: {e}")
            self.errors_count += 1
            raise
    
    def _detect_brand(self, text: str) -> Optional[str]:
        """Détecte la marque mentionnée dans le texte"""
        text_lower = text.lower()
        for brand in self.config.brand_variants:
            if brand.lower() in text_lower:
                return brand
        return None
    
    def _detect_theme(self, text: str) -> Optional[str]:
        """Détecte le thème mentionné dans le texte"""
        text_lower = text.lower()
        for theme in self.config.themes:
            if theme.lower() in text_lower:
                return theme
        return None
    
    @property
    @abstractmethod
    def source_type(self) -> str:
        """Type de source (forum, review, serp, qa)"""
        pass
    
    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """Vérifie si ce scraper est activé dans la config"""
        pass
    
    @abstractmethod
    def run(self) -> List[RawItem]:
        """Exécute le scraping et retourne les items"""
        pass
    
    def get_stats(self) -> dict:
        """Retourne les statistiques du scraper"""
        return {
            "source_type": self.source_type,
            "items_scraped": self.items_scraped,
            "errors_count": self.errors_count
        }
