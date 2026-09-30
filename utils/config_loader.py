import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ClientConfig:
    name: str
    slug: str
    website: str = ""


@dataclass
class ScrapingConfig:
    max_results_per_source: int = 100
    max_results_per_theme: int = 50
    delay_between_requests: int = 2
    max_retries: int = 3
    timeout: int = 30
    forum: Dict[str, Any] = field(default_factory=lambda: {
        "max_threads": 50,
        "max_replies_per_thread": 3,
        "max_thread_depth": 2
    })
    reviews: Dict[str, Any] = field(default_factory=lambda: {
        "max_rating": 3,
        "include_all_ratings": False,
        "min_text_length": 100,
        "max_pages": 10
    })
    serp: Dict[str, Any] = field(default_factory=lambda: {
        "max_paa_depth": 3,
        "max_suggestions": 10
    })


@dataclass
class FiltersConfig:
    min_text_length: int = 50
    max_text_length: int = 5000
    spam_patterns: List[str] = field(default_factory=list)
    required_keywords_mode: str = "any"
    accepted_languages: List[str] = field(default_factory=lambda: ["fr"])


@dataclass
class OutputConfig:
    format: str = "csv"
    include_rejected: bool = True
    fields: List[str] = field(default_factory=lambda: [
        "id", "source_type", "platform", "theme", "brand_detected",
        "raw_text", "url", "title", "rating", "date", "is_question", "sentiment_hint"
    ])


@dataclass
class Config:
    client: ClientConfig
    brand_variants: List[str]
    markets: List[str]
    languages: List[str]
    themes: List[str]
    competitors: List[str]
    sources: Dict[str, Any]
    scraping: ScrapingConfig
    filters: FiltersConfig
    output: OutputConfig
    
    @property
    def all_keywords(self) -> List[str]:
        """Retourne tous les mots-clés de recherche (marques + thèmes)"""
        return self.brand_variants + self.themes


def load_config(config_path: str) -> Config:
    """Charge et valide la configuration depuis un fichier YAML"""
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
    
    client = ClientConfig(
        name=raw.get('client', {}).get('name', 'Unknown'),
        slug=raw.get('client', {}).get('slug', 'unknown'),
        website=raw.get('client', {}).get('website', '')
    )
    
    scraping_raw = raw.get('scraping', {})
    scraping = ScrapingConfig(
        max_results_per_source=scraping_raw.get('max_results_per_source', 100),
        max_results_per_theme=scraping_raw.get('max_results_per_theme', 50),
        delay_between_requests=scraping_raw.get('delay_between_requests', 2),
        max_retries=scraping_raw.get('max_retries', 3),
        timeout=scraping_raw.get('timeout', 30),
        forum=scraping_raw.get('forum', {}),
        reviews=scraping_raw.get('reviews', {}),
        serp=scraping_raw.get('serp', {})
    )
    
    filters_raw = raw.get('filters', {})
    filters = FiltersConfig(
        min_text_length=filters_raw.get('min_text_length', 50),
        max_text_length=filters_raw.get('max_text_length', 5000),
        spam_patterns=filters_raw.get('spam_patterns', []),
        required_keywords_mode=filters_raw.get('required_keywords_mode', 'any'),
        accepted_languages=filters_raw.get('accepted_languages', ['fr'])
    )
    
    output_raw = raw.get('output', {})
    output = OutputConfig(
        format=output_raw.get('format', 'csv'),
        include_rejected=output_raw.get('include_rejected', True),
        fields=output_raw.get('fields', [])
    )
    
    return Config(
        client=client,
        brand_variants=raw.get('brand_variants', []),
        markets=raw.get('markets', ['FR']),
        languages=raw.get('languages', ['fr']),
        themes=raw.get('themes', []),
        competitors=raw.get('competitors', []),
        sources=raw.get('sources', {}),
        scraping=scraping,
        filters=filters,
        output=output
    )
