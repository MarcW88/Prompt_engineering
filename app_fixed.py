"""
Prompt Finder - Interface Hugging Face Spaces (Autonome)
Collecte de questions et avis pour analyse GEO
"""

import gradio as gr
import pandas as pd
import tempfile
import os
import re
import time
import json
import base64
import hashlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set, Tuple
from enum import Enum
import uuid
import csv

from dotenv import load_dotenv
load_dotenv()

# Dossier d'exports persistant (évite la suppression rapide des fichiers temporaires)
EXPORTS_DIR = Path(__file__).parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import hdbscan
    HDBSCAN_AVAILABLE = True
except ImportError:
    HDBSCAN_AVAILABLE = False


# ============================================
# MODELS
# ============================================

class SourceType(Enum):
    FORUM = "forum"
    REVIEW = "review"
    SERP = "serp"
    QA = "qa"
    GSC_CONVERSATION = "gsc_conversation"


@dataclass
class RawItem:
    source_type: SourceType
    platform: str
    raw_text: str
    url: str
    title: str = ""
    author: str = ""
    date: Optional[datetime] = None
    rating: Optional[float] = None
    brand: str = ""
    theme: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    client_slug: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_type": self.source_type.value,
            "platform": self.platform,
            "raw_text": self.raw_text,
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "date": self.date.isoformat() if self.date else None,
            "rating": self.rating,
            "brand": self.brand,
            "theme": self.theme,
            "metadata": self.metadata,
            "client_slug": self.client_slug
        }


# ============================================
# SIMPLE CONFIG
# ============================================

@dataclass
class SimpleConfig:
    client_name: str
    client_slug: str
    keywords: List[str]
    subreddits: List[str]
    forums: List[Dict]
    trustpilot_url: str
    max_posts_per_subreddit: int
    max_results_per_forum: int
    max_trustpilot_pages: int
    max_serp_results: int
    location_code: int = 2056
    language_code: str = "fr"
    min_text_length: int = 30
    max_text_length: int = 10000
    delay_between_requests: float = 2.0


# ============================================
# REDDIT SCRAPER (via DataForSEO)
# ============================================

def scrape_reddit(config: SimpleConfig, logs: List[str], progress_callback=None) -> List[RawItem]:
    """Scrape Reddit via DataForSEO (contourne le blocage 403 sur HF Spaces)"""
    items = []
    
    logs.append(f"   📋 Subreddits: {config.subreddits}")
    logs.append(f"   📋 Keywords (5 premiers): {config.keywords[:5]}")
    
    if not config.subreddits:
        logs.append("   ⚠️ Aucun subreddit configuré")
        return items
    
    if not config.keywords:
        logs.append("   ⚠️ Aucun keyword configuré")
        return items
    
    login = os.getenv("DATAFORSEO_LOGIN")
    password = os.getenv("DATAFORSEO_PASSWORD")
    
    if not login or not password:
        logs.append("   ⚠️ DataForSEO non configuré - requis pour Reddit sur HF")
        return items
    
    auth_string = f"{login}:{password}"
    auth_header = f"Basic {base64.b64encode(auth_string.encode()).decode()}"
    
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }
    
    keywords_to_use = config.keywords[:5]
    total_ops = len(config.subreddits) * len(keywords_to_use)
    current_op = 0
    
    for subreddit in config.subreddits:
        subreddit = subreddit.strip().lstrip('r/')
        
        for keyword in keywords_to_use:
            # Mise à jour progression
            if progress_callback:
                progress_callback(current_op / total_ops, f"Reddit: r/{subreddit} + '{keyword}'")
            current_op += 1
            try:
                query = f"site:reddit.com/r/{subreddit} {keyword}"
                logs.append(f"   🔍 r/{subreddit} + '{keyword}'...")
                
                payload = [{
                    "keyword": query,
                    "location_code": config.location_code,
                    "language_code": config.language_code,
                    "device": "desktop",
                    "os": "windows",
                    "depth": min(config.max_posts_per_subreddit // len(keywords_to_use), 10)
                }]
                
                time.sleep(config.delay_between_requests)
                
                response = requests.post(
                    "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                
                if response.status_code != 200:
                    logs.append(f"   ❌ HTTP {response.status_code}")
                    continue
                
                result = response.json()
                if result.get("status_code") != 20000:
                    continue
                
                tasks = result.get("tasks", [])
                if not tasks:
                    continue
                
                task_result = tasks[0].get("result", [])
                if not task_result:
                    continue
                
                first_result = task_result[0]
                if not first_result:
                    continue
                
                serp_items = first_result.get("items") or []
                count = 0
                
                for serp_item in serp_items:
                    if not isinstance(serp_item, dict):
                        continue
                    
                    if serp_item.get("type") == "organic":
                        title = serp_item.get("title", "")
                        snippet = serp_item.get("description", "")
                        item_url = serp_item.get("url", "")
                        full_text = f"{title}\n\n{snippet}".strip()
                        
                        if len(full_text) >= 20 and "reddit.com" in item_url:
                            item = RawItem(
                                source_type=SourceType.FORUM,
                                platform="reddit",
                                raw_text=full_text,
                                url=item_url,
                                title=title,
                                metadata={"subreddit": subreddit, "search_term": keyword},
                                client_slug=config.client_slug
                            )
                            items.append(item)
                            count += 1
                
                logs.append(f"   → {count} posts trouvés")
                
            except Exception as e:
                logs.append(f"   ⚠️ Erreur r/{subreddit}: {str(e)[:50]}")
    
    return items


# ============================================
# TRUSTPILOT SCRAPER
# ============================================

def scrape_trustpilot(config: SimpleConfig, logs: List[str], progress_callback=None) -> List[RawItem]:
    """Scrape Trustpilot via HTML"""
    items = []
    
    if not config.trustpilot_url:
        return items
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    total_pages = config.max_trustpilot_pages
    for page in range(1, config.max_trustpilot_pages + 1):
        # Mise à jour progression
        if progress_callback:
            progress_callback((page - 1) / total_pages, f"Trustpilot: page {page}/{total_pages}")
        try:
            url = f"{config.trustpilot_url}?page={page}"
            time.sleep(config.delay_between_requests)
            
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                break
            
            soup = BeautifulSoup(response.text, "lxml")
            review_cards = soup.select("article[data-service-review-card-paper]")
            
            if not review_cards:
                review_cards = soup.select(".review-card, [class*='review']")
            
            for card in review_cards:
                try:
                    title_el = card.select_one("h2, [data-service-review-title-typography]")
                    title = title_el.get_text(strip=True) if title_el else ""
                    
                    content_el = card.select_one("p[data-service-review-text-typography], .review-content")
                    content = content_el.get_text(strip=True) if content_el else ""
                    
                    rating = None
                    rating_el = card.select_one("[data-service-review-rating], .star-rating")
                    if rating_el:
                        rating_img = rating_el.select_one("img")
                        if rating_img and rating_img.get("alt"):
                            match = re.search(r"(\d)", rating_img.get("alt", ""))
                            if match:
                                rating = float(match.group(1))
                    
                    date = None
                    date_el = card.select_one("time")
                    if date_el and date_el.get("datetime"):
                        try:
                            date = datetime.fromisoformat(date_el["datetime"].replace("Z", "+00:00"))
                        except:
                            pass
                    
                    full_text = f"{title}\n\n{content}".strip()
                    
                    if len(full_text) >= config.min_text_length:
                        item = RawItem(
                            source_type=SourceType.REVIEW,
                            platform="trustpilot",
                            raw_text=full_text,
                            url=url,
                            title=title,
                            rating=rating,
                            date=date,
                            client_slug=config.client_slug
                        )
                        items.append(item)
                        
                except Exception:
                    continue
            
            logs.append(f"   Page {page}: {len(review_cards)} avis")
            
        except Exception as e:
            logs.append(f"   ⚠️ Erreur page {page}: {str(e)[:50]}")
            break
    
    return items


# ============================================
# FORUMS SCRAPER (via DataForSEO)
# ============================================

def scrape_forums(config: SimpleConfig, logs: List[str], progress_callback=None) -> List[RawItem]:
    """Scrape forums génériques via DataForSEO - site:domain + keyword"""
    items = []
    
    if not config.forums:
        logs.append("   ⚠️ Aucun forum configuré")
        return items
    
    if not config.keywords:
        logs.append("   ⚠️ Aucun keyword configuré")
        return items
    
    login = os.getenv("DATAFORSEO_LOGIN")
    password = os.getenv("DATAFORSEO_PASSWORD")
    
    if not login or not password:
        logs.append("   ⚠️ DataForSEO non configuré - requis pour forums")
        return items
    
    auth_string = f"{login}:{password}"
    auth_header = f"Basic {base64.b64encode(auth_string.encode()).decode()}"
    
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }
    
    keywords_to_use = config.keywords[:5]
    total_ops = len(config.forums) * len(keywords_to_use)
    current_op = 0
    
    for forum in config.forums:
        forum_name = forum.get("name", "forum")
        forum_url = forum.get("url", "")
        
        if not forum_url:
            continue
        
        domain = forum_url.replace("https://", "").replace("http://", "").split("/")[0]
        
        for keyword in keywords_to_use:
            # Mise à jour progression
            if progress_callback:
                progress_callback(current_op / total_ops, f"Forums: {forum_name} + '{keyword}'")
            current_op += 1
            try:
                query = f"site:{domain} {keyword}"
                logs.append(f"   🔍 {forum_name} + '{keyword}'...")
                
                payload = [{
                    "keyword": query,
                    "location_code": config.location_code,
                    "language_code": config.language_code,
                    "device": "desktop",
                    "os": "windows",
                    "depth": min(config.max_results_per_forum // len(keywords_to_use), 10)
                }]
                
                time.sleep(config.delay_between_requests)
                
                response = requests.post(
                    "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                
                if response.status_code != 200:
                    logs.append(f"   ❌ HTTP {response.status_code}")
                    continue
                
                result = response.json()
                if result.get("status_code") != 20000:
                    continue
                
                tasks = result.get("tasks", [])
                if not tasks:
                    continue
                
                task_result = tasks[0].get("result", [])
                if not task_result:
                    continue
                
                first_result = task_result[0]
                if not first_result:
                    continue
                
                serp_items = first_result.get("items") or []
                count = 0
                
                for serp_item in serp_items:
                    if not isinstance(serp_item, dict):
                        continue
                    
                    if serp_item.get("type") == "organic":
                        title = serp_item.get("title", "")
                        snippet = serp_item.get("description", "")
                        item_url = serp_item.get("url", "")
                        full_text = f"{title}\n\n{snippet}".strip()
                        
                        if len(full_text) >= 20:
                            item = RawItem(
                                source_type=SourceType.FORUM,
                                platform=forum_name,
                                raw_text=full_text,
                                url=item_url,
                                title=title,
                                metadata={"forum": forum_name, "domain": domain, "search_term": keyword},
                                client_slug=config.client_slug
                            )
                            items.append(item)
                            count += 1
                
                logs.append(f"   → {count} résultats")
                
            except Exception as e:
                logs.append(f"   ⚠️ Erreur {forum_name}: {str(e)[:50]}")
    
    return items


# ============================================
# SERP/PAA SCRAPER (DataForSEO)
# ============================================

def scrape_serp(config: SimpleConfig, logs: List[str], progress_callback=None) -> List[RawItem]:
    """Scrape PAA via DataForSEO"""
    items = []
    seen_questions = set()
    
    login = os.getenv("DATAFORSEO_LOGIN")
    password = os.getenv("DATAFORSEO_PASSWORD")
    
    if not login or not password:
        logs.append("   ⚠️ DataForSEO non configuré")
        return items
    
    auth_string = f"{login}:{password}"
    auth_header = f"Basic {base64.b64encode(auth_string.encode()).decode()}"
    
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }
    
    keywords_to_process = config.keywords[:config.max_serp_results]
    total_keywords = len(keywords_to_process)
    
    for idx, keyword in enumerate(keywords_to_process):
        # Mise à jour progression
        if progress_callback:
            progress_callback(idx / total_keywords, f"SERP/PAA: '{keyword[:30]}...' ({idx+1}/{total_keywords})")
        try:
            payload = [{
                "keyword": keyword,
                "location_code": config.location_code,
                "language_code": config.language_code,
                "device": "desktop",
                "os": "windows"
            }]
            
            time.sleep(config.delay_between_requests)
            
            response = requests.post(
                "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
                json=payload,
                headers=headers,
                timeout=60
            )
            
            if response.status_code != 200:
                continue
            
            result = response.json()
            
            if result.get("status_code") != 20000:
                continue
            
            tasks = result.get("tasks", [])
            if not tasks:
                continue
            
            task_result = tasks[0].get("result", [])
            if not task_result:
                continue
            
            serp_items = task_result[0].get("items", [])
            
            for serp_item in serp_items:
                if not isinstance(serp_item, dict):
                    continue
                
                if serp_item.get("type") == "people_also_ask":
                    paa_items = serp_item.get("items", [])
                    if not isinstance(paa_items, list):
                        continue
                    
                    for paa in paa_items[:4]:
                        if not isinstance(paa, dict):
                            continue
                        
                        q_text = paa.get("title", "")
                        if q_text and q_text.lower() not in seen_questions:
                            seen_questions.add(q_text.lower())
                            
                            item = RawItem(
                                source_type=SourceType.SERP,
                                platform="google_paa",
                                raw_text=q_text,
                                url=f"https://google.fr/search?q={keyword}",
                                title=q_text,
                                metadata={"query": keyword, "type": "paa"},
                                client_slug=config.client_slug
                            )
                            items.append(item)
            
        except Exception as e:
            logs.append(f"   ⚠️ Erreur SERP '{keyword[:20]}': {str(e)[:50]}")
    
    return items


# ============================================
# GSC CONVERSATIONS PARSER
# ============================================

def parse_gsc_csv(file_obj, min_words: int = 10, client_slug: str = "") -> Tuple[List[RawItem], List[str]]:
    """Parse un export CSV de Google Search Console et filtre les queries conversationnelles (10+ mots)
    
    Le CSV GSC standard contient: Top queries, Clicks, Impressions, CTR, Position
    """
    items = []
    logs = []
    
    if file_obj is None:
        return items, logs
    
    try:
        # GSC exporte souvent en format avec différents séparateurs ou encodages
        # Essayer plusieurs configurations
        df = None
        for sep in [',', '\t', ';']:
            for encoding in ['utf-8', 'utf-16', 'latin-1']:
                try:
                    df = pd.read_csv(file_obj.name, sep=sep, encoding=encoding, on_bad_lines='skip')
                    if len(df.columns) >= 1 and len(df) > 0:
                        break
                except:
                    continue
            if df is not None and len(df.columns) >= 1:
                break
        
        if df is None or len(df) == 0:
            logs.append("   ❌ Impossible de parser le fichier CSV GSC")
            return items, logs
        
        logs.append(f"   📂 {len(df)} lignes chargées depuis GSC")
        
        # Détecter la colonne de queries (peut être "Top queries", "Query", "Queries", etc.)
        query_col = None
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in ['top queries', 'query', 'queries', 'search query', 'requête', 'requêtes']:
                query_col = col
                break
        
        if query_col is None:
            # Prendre la première colonne par défaut
            query_col = df.columns[0]
            logs.append(f"   ⚠️ Colonne 'Query' non trouvée, utilisation de '{query_col}'")
        
        # Filtrer les queries avec 10+ mots
        def count_words(text):
            if pd.isna(text):
                return 0
            return len(str(text).split())
        
        df['word_count'] = df[query_col].apply(count_words)
        conversational = df[df['word_count'] >= min_words]
        
        logs.append(f"   🔍 {len(conversational)} queries avec {min_words}+ mots (sur {len(df)} total)")
        
        # Créer les RawItems
        for _, row in conversational.iterrows():
            query = str(row[query_col]).strip()
            
            # Récupérer les métriques si disponibles
            clicks = row.get('Clicks', row.get('clicks', 0))
            impressions = row.get('Impressions', row.get('impressions', 0))
            
            item = RawItem(
                source_type=SourceType.GSC_CONVERSATION,
                platform="google_search_console",
                raw_text=query,
                url="https://search.google.com",
                title=query,
                metadata={
                    "word_count": row['word_count'],
                    "clicks": int(clicks) if pd.notna(clicks) else 0,
                    "impressions": int(impressions) if pd.notna(impressions) else 0
                },
                client_slug=client_slug
            )
            items.append(item)
        
        logs.append(f"   ✅ {len(items)} queries conversationnelles extraites")
        
    except Exception as e:
        logs.append(f"   ❌ Erreur parsing GSC: {str(e)}")
    
    return items, logs


# ============================================
# QUALITY FILTER
# ============================================

def filter_items(items: List[RawItem], config: SimpleConfig) -> Tuple[List[RawItem], int]:
    """Filtre les items par qualité"""
    accepted = []
    seen_hashes = set()
    rejected_count = 0
    
    for item in items:
        text = item.raw_text
        
        if len(text) < config.min_text_length or len(text) > config.max_text_length:
            rejected_count += 1
            continue
        
        text_hash = hashlib.md5(text.lower().encode()).hexdigest()
        if text_hash in seen_hashes:
            rejected_count += 1
            continue
        seen_hashes.add(text_hash)
        
        spam_patterns = ["cliquez ici", "code promo", "lien affilié"]
        is_spam = any(p in text.lower() for p in spam_patterns)
        if is_spam:
            rejected_count += 1
            continue
        
        accepted.append(item)
    
    return accepted, rejected_count


# ============================================
# ENRICHMENT & EXPORT
# ============================================

QUESTION_PATTERNS = [
    r"^(comment|pourquoi|quand|où|qui|quel|quelle|quels|quelles|combien|est-ce que|qu'est-ce)",
    r"\?$",
    r"^(how|why|when|where|who|what|which|can|could|should|would|is|are|do|does)"
]

NEGATIVE_KEYWORDS = ["problème", "arnaque", "nul", "horrible", "catastrophe", "déçu", "mauvais"]


def is_question(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower().strip()
    for pattern in QUESTION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def detect_sentiment(item: RawItem) -> str:
    if item.rating is not None:
        if item.rating <= 2:
            return "negative"
        elif item.rating >= 4:
            return "positive"
    
    text_lower = item.raw_text.lower()
    for kw in NEGATIVE_KEYWORDS:
        if kw in text_lower:
            return "negative"
    
    return "neutral"


def export_to_csv(items: List[RawItem], filename: str) -> str:
    """Exporte vers CSV avec enrichissement"""
    output_path = EXPORTS_DIR / filename
    
    fields = ["id", "source_type", "platform", "theme", "brand_detected", 
              "raw_text", "url", "title", "rating", "date", "is_question", "sentiment_hint"]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        
        for item in items:
            row = item.to_dict()
            row["is_question"] = is_question(item.raw_text)
            row["sentiment_hint"] = detect_sentiment(item)
            row["brand_detected"] = row.get("brand", "")
            writer.writerow(row)
    
    return str(output_path)


# ============================================
# MAIN FUNCTIONS
# ============================================

def parse_keywords_file(file_obj) -> list:
    """Parse un fichier Excel/CSV avec colonne 'keywords'"""
    if file_obj is None:
        return []
    
    try:
        if file_obj.name.endswith('.xlsx') or file_obj.name.endswith('.xls'):
            df = pd.read_excel(file_obj.name)
        else:
            df = pd.read_csv(file_obj.name)
        
        keyword_col = None
        for col in df.columns:
            if col.lower().strip() in ['keywords', 'keyword', 'mot-clé', 'mots-clés']:
                keyword_col = col
                break
        
        if keyword_col is None:
            keyword_col = df.columns[0]
        
        keywords = df[keyword_col].dropna().astype(str).tolist()
        keywords = [k.strip() for k in keywords if k.strip()]
        
        return keywords
    except Exception as e:
        return []


def preview_keywords(file_obj):
    """Prévisualise les keywords du fichier uploadé"""
    keywords = parse_keywords_file(file_obj)
    if not keywords:
        return "❌ Aucun keyword trouvé. Vérifiez que le fichier contient une colonne 'keywords'."
    
    preview = f"✅ **{len(keywords)} keywords trouvés**\n\n"
    preview += "Aperçu (10 premiers):\n"
    for i, kw in enumerate(keywords[:10], 1):
        preview += f"{i}. {kw}\n"
    if len(keywords) > 10:
        preview += f"... et {len(keywords) - 10} autres"
    
    return preview


def run_scraping(
    client_name: str,
    keywords_file,
    max_keywords: int,
    subreddits: str,
    forums: str,
    trustpilot_url: str,
    max_posts_per_subreddit: int,
    max_results_per_forum: int,
    max_trustpilot_pages: int,
    max_serp_results: int,
    enable_reddit: bool,
    enable_forums: bool,
    enable_trustpilot: bool,
    enable_serp: bool,
    language_region: str,
    enable_gsc: bool = False,
    gsc_file = None,
    min_words_gsc: int = 10,
    progress=gr.Progress()
):
    """Exécute le scraping"""
    
    if not client_name:
        return None, "❌ Veuillez entrer un nom de client."
    
    keywords = parse_keywords_file(keywords_file)
    
    # Keywords requis sauf si GSC est activé (GSC n'a pas besoin de keywords)
    if not keywords and not (enable_gsc and gsc_file):
        return None, "❌ Veuillez uploader un fichier Excel/CSV avec une colonne 'keywords' (ou activer GSC Conversations)."
    
    keywords = keywords[:max_keywords]
    
    subreddit_list = [s.strip() for s in subreddits.split(",") if s.strip()] if enable_reddit else []
    
    forum_list = []
    if enable_forums and forums.strip():
        for line in forums.strip().split("\n"):
            line = line.strip()
            if line:
                parts = line.split("|")
                if len(parts) >= 2:
                    forum_list.append({"name": parts[0].strip(), "url": parts[1].strip()})
    
    logs = []
    
    # Déterminer location_code et language_code selon la langue
    location_code = 2056  # Belgique par défaut
    if language_region and "NL" in language_region:
        language_code = "nl"
        logs.append(f"🌍 Langue: NL (Néerlandais)")
    elif language_region and "EN" in language_region:
        language_code = "en"
        logs.append(f"🌍 Langue: EN (Anglais)")
    else:
        language_code = "fr"
        logs.append(f"🌍 Langue: FR (Français)")
    
    config = SimpleConfig(
        client_name=client_name,
        client_slug=client_name.lower().replace(" ", "_"),
        keywords=keywords,
        subreddits=subreddit_list,
        forums=forum_list,
        trustpilot_url=trustpilot_url if enable_trustpilot else "",
        max_posts_per_subreddit=max_posts_per_subreddit,
        max_results_per_forum=max_results_per_forum,
        max_trustpilot_pages=max_trustpilot_pages,
        max_serp_results=max_serp_results if enable_serp else 0,
        location_code=location_code,
        language_code=language_code
    )
    
    logs.append(f"📋 Client: {client_name}")
    logs.append(f"🔑 Keywords: {len(keywords)}")
    logs.append("")
    
    all_items = []
    
    # Calculer les plages de progression pour chaque source
    sources_enabled = []
    if enable_reddit and subreddit_list:
        sources_enabled.append("reddit")
    if enable_forums and forum_list:
        sources_enabled.append("forums")
    if enable_serp and max_serp_results > 0:
        sources_enabled.append("serp")
    if enable_trustpilot and trustpilot_url:
        sources_enabled.append("trustpilot")
    if enable_gsc and gsc_file:
        sources_enabled.append("gsc")
    
    # Répartir 0-90% entre les sources (10% réservé pour export)
    total_sources = len(sources_enabled) if sources_enabled else 1
    progress_per_source = 0.85 / total_sources
    current_base = 0.05
    
    try:
        # Reddit
        if enable_reddit and subreddit_list:
            base_progress = current_base
            logs.append(f"🔍 Reddit: {len(subreddit_list)} subreddits")
            
            def reddit_progress(pct, desc):
                progress(base_progress + pct * progress_per_source, desc=desc)
            
            reddit_items = scrape_reddit(config, logs, reddit_progress)
            all_items.extend(reddit_items)
            logs.append(f"   ✅ {len(reddit_items)} posts collectés")
            current_base += progress_per_source
        
        # Forums
        if enable_forums and forum_list:
            base_progress = current_base
            logs.append(f"🔍 Forums: {len(forum_list)} forums")
            
            def forums_progress(pct, desc):
                progress(base_progress + pct * progress_per_source, desc=desc)
            
            forum_items = scrape_forums(config, logs, forums_progress)
            all_items.extend(forum_items)
            logs.append(f"   ✅ {len(forum_items)} posts collectés")
            current_base += progress_per_source
        
        # SERP/PAA
        if enable_serp and max_serp_results > 0:
            base_progress = current_base
            logs.append(f"🔍 SERP/PAA: {max_serp_results} keywords...")
            
            def serp_progress(pct, desc):
                progress(base_progress + pct * progress_per_source, desc=desc)
            
            serp_items = scrape_serp(config, logs, serp_progress)
            all_items.extend(serp_items)
            logs.append(f"   ✅ {len(serp_items)} questions PAA")
            current_base += progress_per_source
        
        # Trustpilot
        if enable_trustpilot and trustpilot_url:
            base_progress = current_base
            logs.append(f"🔍 Trustpilot: {max_trustpilot_pages} pages")
            
            def trustpilot_progress(pct, desc):
                progress(base_progress + pct * progress_per_source, desc=desc)
            
            tp_items = scrape_trustpilot(config, logs, trustpilot_progress)
            all_items.extend(tp_items)
            logs.append(f"   ✅ {len(tp_items)} avis collectés")
            current_base += progress_per_source
        
        # GSC Conversations
        if enable_gsc and gsc_file:
            progress(current_base, desc="Parsing GSC Conversations...")
            logs.append(f"🔍 GSC Conversations (queries {min_words_gsc}+ mots)...")
            gsc_items, gsc_logs = parse_gsc_csv(gsc_file, min_words_gsc, config.client_slug)
            logs.extend(gsc_logs)
            all_items.extend(gsc_items)
            current_base += progress_per_source
        
        if not all_items:
            return None, "\n".join(logs) + "\n\n❌ Aucun item collecté."
        
        progress(0.9, desc="Filtrage et export...")
        
        logs.append("")
        accepted, rejected = filter_items(all_items, config)
        logs.append(f"📊 Filtrage: {len(accepted)} acceptés, {rejected} rejetés")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"etape1_collecte_{config.client_slug}_{timestamp}.csv"
        output_path = export_to_csv(accepted, filename)
        
        progress(1.0, desc="Terminé!")
        
        logs.append("")
        logs.append(f"✅ **Export terminé: {len(accepted)} items**")
        
        return output_path, "\n".join(logs)
        
    except Exception as e:
        import traceback
        return None, f"❌ Erreur: {str(e)}\n\n{traceback.format_exc()}"


# ============================================
# TRANSFORMATION FORUMS → QUESTIONS (Onglet 2)
# ============================================

def get_transform_system_prompt(language_code: str = "fr") -> str:
    """Génère le prompt système de transformation selon la langue"""
    
    lang_instructions = {
        "fr": {
            "lang_name": "français",
            "examples": [
                "Quels sont les bienfaits du collagène marin pour la peau ?",
                "Est-ce que la glutamine aide vraiment pour la récupération musculaire ?",
                "Quels compléments alimentaires prendre pour améliorer le sommeil ?"
            ]
        },
        "nl": {
            "lang_name": "néerlandais (Nederlands)",
            "examples": [
                "Wat zijn de voordelen van mariene collageen voor de huid?",
                "Helpt glutamine echt bij spierherstel?",
                "Welke voedingssupplementen kan ik nemen om beter te slapen?"
            ]
        },
        "en": {
            "lang_name": "anglais (English)",
            "examples": [
                "What are the benefits of marine collagen for the skin?",
                "Does glutamine really help with muscle recovery?",
                "What supplements should I take to improve sleep?"
            ]
        }
    }
    
    lang = lang_instructions.get(language_code, lang_instructions["fr"])
    examples_str = "\n".join([f'- "{ex}"' for ex in lang["examples"]])
    
    return f"""Tu es un expert en analyse de contenu et génération de questions pour l'optimisation GEO (Generative Engine Optimization).

Ta mission : transformer des discussions de forums/Reddit en questions que les utilisateurs poseraient naturellement à un assistant IA comme ChatGPT.

⚠️ RÈGLE CRITIQUE : Tu DOIS générer les questions en {lang["lang_name"]}. NE PAS mélanger les langues.

CRITÈRES pour les questions générées :
1. Proche du langage utilisateur (conversationnel, pas trop SEO)
2. Assez large pour englober plusieurs intentions similaires
3. Assez spécifique pour refléter une intention claire
4. Neutre/sans marque (pour tester si une marque émerge naturellement)
5. OBLIGATOIREMENT en {lang["lang_name"]}

EXEMPLES de bonnes questions (en {lang["lang_name"]}) :
{examples_str}

FORMAT DE SORTIE : Retourne UNIQUEMENT un JSON avec cette structure :
{{
    "questions": ["Question 1", "Question 2", "Question 3"],
    "theme_detected": "thème principal détecté"
}}

Génère 1 à 3 questions pertinentes par contenu EN {lang["lang_name"].upper()}. Si le contenu n'est pas exploitable, retourne un tableau vide."""


def transform_content_to_questions(client, text: str, title: str, platform: str, language_code: str = "fr") -> dict:
    """Transforme un contenu en questions via OpenAI"""
    user_prompt = f"""Contenu à analyser (source: {platform}):

Titre: {title}

Texte: {text}

Génère des questions GEO pertinentes basées sur ce contenu."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": get_transform_system_prompt(language_code)},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        return json.loads(content)
        
    except Exception as e:
        return {"questions": [], "theme_detected": "", "error": str(e)}


def run_transformation(
    input_file,
    openai_api_key: str,
    language_region: str = "FR - Français",
    progress=gr.Progress()
):
    """Transforme les contenus forums en questions"""
    logs = []
    
    if not OPENAI_AVAILABLE:
        return None, "❌ OpenAI non installé. Exécutez: pip install openai"
    
    if not input_file:
        return None, "❌ Veuillez uploader un fichier CSV (export de l'étape 1)"
    
    # Utiliser la clé fournie OU la variable d'environnement HF
    api_key = openai_api_key or os.getenv("OPENAI_SECRET_KEY") or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        return None, "❌ Clé API OpenAI non trouvée. Entrez-la ci-dessus ou configurez OPENAI_SECRET_KEY dans les secrets HF."
    
    try:
        # Charger le CSV
        logs.append("📂 Chargement du fichier...")
        df = pd.read_csv(input_file.name)
        logs.append(f"   ✅ {len(df)} lignes chargées")
        
        # Convertir is_question en boolean
        df['is_question'] = df['is_question'].astype(str).str.lower().isin(['true', '1', 'yes'])
        
        # Séparer questions existantes (PAA + GSC) et contenus à transformer (forums + trustpilot)
        # GSC conversations sont déjà des questions (queries 10+ mots), pas besoin de transformation
        sources_to_keep = ['serp', 'gsc_conversation']
        existing_questions = df[df['source_type'].isin(sources_to_keep)].copy()
        # Inclure forums ET reviews (trustpilot) dans la transformation
        sources_to_transform = ['forum', 'review']
        content_to_transform = df[df['source_type'].isin(sources_to_transform)].copy()
        
        logs.append(f"📊 Questions existantes (PAA + GSC): {len(existing_questions)}")
        logs.append(f"📊 Contenus à transformer (forums + trustpilot): {len(content_to_transform)}")
        
        # Afficher les sources détectées
        if len(content_to_transform) > 0:
            content_sources = content_to_transform['platform'].value_counts()
            for source, count in content_sources.items():
                logs.append(f"   - {source}: {count} items")
        
        if len(content_to_transform) == 0:
            logs.append("⚠️ Aucun contenu à transformer")
            # Retourner juste les questions existantes (PAA + GSC)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = EXPORTS_DIR / f"etape2_questions_only_{timestamp}.csv"
            existing_questions.to_csv(output_path, index=False)
            return str(output_path), "\n".join(logs)
        
        # Déterminer la langue
        if language_region and "NL" in language_region:
            language_code = "nl"
            logs.append("🌍 Langue de génération: NL (Néerlandais)")
        elif language_region and "EN" in language_region:
            language_code = "en"
            logs.append("🌍 Langue de génération: EN (Anglais)")
        else:
            language_code = "fr"
            logs.append("🌍 Langue de génération: FR (Français)")
        
        # Initialiser OpenAI
        progress(0.1, desc="Connexion OpenAI...")
        client = OpenAI(api_key=api_key)
        logs.append("🔑 Connexion OpenAI OK")
        
        # Transformer les contenus
        logs.append("")
        logs.append("🤖 Transformation via GPT-4o-mini...")
        
        generated_questions = []
        total = len(content_to_transform)
        
        for idx, (_, row) in enumerate(content_to_transform.iterrows()):
            progress((0.1 + 0.8 * idx / total), desc=f"Transformation {idx+1}/{total}...")
            
            title_short = row['title'][:40] if pd.notna(row['title']) else "Sans titre"
            logs.append(f"   [{idx+1}/{total}] {row['platform']}: {title_short}...")
            
            result = transform_content_to_questions(
                client,
                str(row['raw_text']) if pd.notna(row['raw_text']) else "",
                str(row['title']) if pd.notna(row['title']) else "",
                str(row['platform']) if pd.notna(row['platform']) else "",
                language_code
            )
            
            original_platform = str(row['platform']) if pd.notna(row['platform']) else 'unknown'
            for q_idx, question in enumerate(result.get('questions', [])):
                generated_questions.append({
                    'id': f"gen_{idx}_{q_idx}",
                    'source_type': 'generated',
                    'platform': original_platform,  # Garde le nom du forum original (doctissimo, davidmanise, reddit, etc.)
                    'theme': result.get('theme_detected', ''),
                    'brand_detected': '',
                    'raw_text': question,
                    'url': row['url'] if pd.notna(row['url']) else '',
                    'title': question,
                    'rating': None,
                    'date': None,
                    'is_question': True,
                    'sentiment_hint': 'neutral',
                    'original_title': row['title'] if pd.notna(row['title']) else ''  # Titre original pour traçabilité
                })
            
            time.sleep(0.3)  # Rate limiting
        
        logs.append(f"   ✅ {len(generated_questions)} questions générées")
        
        # Préparer les questions existantes (PAA + GSC) pour la fusion
        questions_for_export = existing_questions[['id', 'source_type', 'platform', 'theme', 
                                         'brand_detected', 'raw_text', 'url', 'title',
                                         'rating', 'date', 'is_question', 'sentiment_hint']].copy()
        questions_for_export['original_title'] = ''  # PAA/GSC n'ont pas de titre original
        
        # Créer DataFrame des questions générées
        generated_df = pd.DataFrame(generated_questions)
        
        # Fusionner
        progress(0.95, desc="Export...")
        final_df = pd.concat([questions_for_export, generated_df], ignore_index=True)
        
        # Sauvegarder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = EXPORTS_DIR / f"etape2_questions_geo_{timestamp}.csv"
        final_df.to_csv(output_path, index=False)
        output_path = str(output_path)
        
        progress(1.0, desc="Terminé!")
        
        logs.append("")
        logs.append("="*50)
        logs.append("📊 RÉSUMÉ")
        logs.append("="*50)
        logs.append(f"   Questions existantes (PAA + GSC): {len(questions_for_export)}")
        logs.append(f"   Questions générées: {len(generated_questions)}")
        logs.append(f"   TOTAL: {len(final_df)}")
        logs.append("")
        logs.append(f"✅ Export terminé!")
        
        return output_path, "\n".join(logs)
        
    except Exception as e:
        import traceback
        return None, f"❌ Erreur: {str(e)}\n\n{traceback.format_exc()}"


# ============================================
# ÉTAPE 2B: NORMALISATION (intégrée à la transformation)
# ============================================

# Corrections de coquilles courantes
TYPO_CORRECTIONS = {
    r'\bl[- ]?lyrosine\b': 'L-tyrosine',
    r'\bl[- ]?glutamin\b': 'L-glutamine',
    r'\bglutamin\b': 'glutamine',
    r'\bcreatine\b': 'créatine',
    r'\bproteines?\b': 'protéines',
    r'\bvitamines?\s+d\b': 'vitamine D',
    r'\bomega\s*3\b': 'oméga-3',
    r'\bmagnesium\b': 'magnésium',
    r'\bmelatonine\b': 'mélatonine',
    r'\bmillepertui\b': 'millepertuis',
    r'\binterractions?\b': 'interactions',
    r'\best[- ]?ce\s+que\b': 'est-ce que',
}

CANONICALIZATION_PROMPT = """Tu es un expert en analyse sémantique pour le SEO génératif (GEO).

Je te donne un groupe de questions qui expriment la MÊME intention utilisateur.

Ta tâche:
1. Identifier l'intention commune
2. Choisir ou reformuler UNE question canonique (la plus claire, naturelle, complète)
3. Garder 3-5 variantes naturelles les plus distinctes

Critères pour la question canonique:
- Formulation naturelle (comme un utilisateur poserait la question à ChatGPT)
- Complète mais pas verbeuse
- Neutre (pas de marque)
- Couvre l'intention principale du groupe

Réponds en JSON:
{
    "intent_summary": "description courte de l'intention",
    "canonical_question": "la question canonique choisie",
    "variants": ["variante 1", "variante 2", "variante 3"],
    "confidence": 0.95
}"""

TAGGING_PROMPT = """Analyse cette question et fournis les tags en JSON:
{"intent_type": "information|decision|comparison|safety|howto", "sensitivity": "low|medium|high", "domain": "nutrition|sport|santé|beauté|médical|général", "entities": ["entité1"], "context": "sport|grossesse|enfant|senior|général"}"""


def normalize_text_formal(text: str) -> str:
    """Niveau 1: Normalisation formelle"""
    if not text or not isinstance(text, str):
        return ""
    text = ' '.join(text.split())
    for pattern, replacement in TYPO_CORRECTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r'\s+([?!.,;:])', r'\1', text)
    text = re.sub(r'([?!])+', r'\1', text)
    text = text.strip()
    if text and not text.endswith('?') and not text.endswith('!') and not text.endswith('.'):
        question_starters = ['comment', 'pourquoi', 'quand', 'où', 'qui', 'que', 'quel', 
                            'quelle', 'quels', 'quelles', 'est-ce', "qu'est", 'combien']
        if any(text.lower().startswith(q) for q in question_starters):
            text += ' ?'
    return text


def get_text_hash(text: str) -> str:
    """Hash pour détecter doublons exacts"""
    normalized = text.lower().strip()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = ' '.join(normalized.split())
    return hashlib.md5(normalized.encode()).hexdigest()


def get_embeddings_batch(client, texts: List[str], batch_size: int = 100) -> list:
    """Obtient les embeddings via OpenAI"""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
    return all_embeddings


def canonicalize_group(client, questions: List[str], intent_id: str) -> Dict:
    """Canonicalise un groupe de questions"""
    if len(questions) == 1:
        return {
            "intent_id": intent_id,
            "intent_summary": "",
            "canonical_question": questions[0],
            "variants": [],
            "confidence": 1.0
        }
    
    sample = questions[:10] if len(questions) > 10 else questions
    questions_text = "\n".join([f"- {q}" for q in sample])
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CANONICALIZATION_PROMPT},
                {"role": "user", "content": f"Groupe ({intent_id}):\n\n{questions_text}"}
            ],
            temperature=0.3,
            max_tokens=500
        )
        content = response.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
        result["intent_id"] = intent_id
        return result
    except Exception as e:
        return {
            "intent_id": intent_id,
            "intent_summary": "",
            "canonical_question": questions[0],
            "variants": questions[1:5] if len(questions) > 1 else [],
            "confidence": 0.5
        }


def tag_question_batch(client, questions: List[str]) -> List[Dict]:
    """Tag un batch de questions"""
    results = []
    for q in questions:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": TAGGING_PROMPT},
                    {"role": "user", "content": q}
                ],
                temperature=0.2,
                max_tokens=150
            )
            content = response.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            tags = json.loads(content)
            tags['question'] = q
            results.append(tags)
        except:
            results.append({
                'question': q,
                'intent_type': 'information',
                'sensitivity': 'medium',
                'domain': 'général',
                'entities': [],
                'context': 'général'
            })
    return results


def generate_intent_label(question: str) -> str:
    """Génère un intent_label court à partir d'une question représentative
    
    Exemple: "Comment trouver un job étudiant ?" -> "trouver_job_etudiant"
    """
    import unicodedata
    
    # Normaliser et enlever accents
    text = unicodedata.normalize('NFD', question.lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    
    # Enlever ponctuation et mots vides
    stopwords = {'comment', 'quoi', 'quel', 'quelle', 'quels', 'quelles', 'est', 'ce', 'que', 
                 'qui', 'ou', 'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'a', 'au', 
                 'aux', 'et', 'en', 'pour', 'par', 'sur', 'avec', 'dans', 'son', 'sa', 'ses',
                 'mon', 'ma', 'mes', 'ton', 'ta', 'tes', 'je', 'tu', 'il', 'elle', 'nous', 
                 'vous', 'ils', 'elles', 'on', 'se', 'ne', 'pas', 'plus', 'moins', 'tres',
                 'peut', 'faire', 'faut', 'doit', 'sont', 'etre', 'avoir', 'cette', 'ces',
                 'the', 'a', 'an', 'is', 'are', 'what', 'how', 'why', 'when', 'where', 'which'}
    
    # Garder uniquement lettres et espaces
    text = re.sub(r'[^a-z\s]', '', text)
    
    # Extraire mots significatifs
    words = [w for w in text.split() if w not in stopwords and len(w) > 2]
    
    # Prendre les 4 premiers mots significatifs
    label_words = words[:4]
    
    if not label_words:
        return "intent_general"
    
    return '_'.join(label_words)


def get_classification_prompt(brand_name: str, personas: List[str], products_services: List[str], language_code: str) -> str:
    """Génère le prompt système pour la classification multi-dimensionnelle"""
    
    personas_str = ", ".join(personas) if personas else "Non défini"
    products_str = ", ".join(products_services) if products_services else "Autre"
    
    lang_examples = {
        "fr": {
            "informational": "Qu'est-ce qu'un budget mobilité ?",
            "commercial": "Quel est le meilleur vélo électrique ?",
            "transactional": "Où acheter un vélo Decathlon ?",
            "navigational": "Site officiel Decathlon Belgique"
        },
        "nl": {
            "informational": "Wat is een mobiliteitsbudget?",
            "commercial": "Wat is de beste elektrische fiets?",
            "transactional": "Waar kan ik een Decathlon fiets kopen?",
            "navigational": "Officiële Decathlon België website"
        },
        "en": {
            "informational": "What is a mobility budget?",
            "commercial": "What is the best electric bike?",
            "transactional": "Where to buy a Decathlon bike?",
            "navigational": "Official Decathlon Belgium website"
        }
    }
    
    examples = lang_examples.get(language_code, lang_examples["fr"])
    
    return f"""Tu es un expert en classification de questions pour l'analyse GEO (Generative Engine Optimization).

Pour CHAQUE question, tu dois attribuer les dimensions suivantes :

## 1. USER INTENT (obligatoire)
- **Informational** : L'utilisateur cherche une information, une explication
  Exemple: "{examples['informational']}"
- **Commercial** : L'utilisateur compare, évalue des options avant achat
  Exemple: "{examples['commercial']}"
- **Transactional** : L'utilisateur veut acheter, s'inscrire, agir
  Exemple: "{examples['transactional']}"
- **Navigational** : L'utilisateur cherche un site/page spécifique
  Exemple: "{examples['navigational']}"

## 2. PERSONA (si applicable)
Personas définis : {personas_str}
- Attribue UN persona de la liste ci-dessus
- Si aucun ne correspond, utilise "Non défini"

## 3. PRODUCT/SERVICE (obligatoire)
Produits/Services définis : {products_str}
- Attribue UN produit/service de la liste ci-dessus
- Si aucun ne correspond, utilise "Autre"

## 4. BRAND MENTIONED (obligatoire)
Marque à détecter : "{brand_name}"
- **true** si la marque "{brand_name}" (ou une variante proche) est mentionnée dans la question
- **false** sinon

## 5. FAN-OUT LEVEL (obligatoire)
- **0** : Question générique/large (ex: "Qu'est-ce que le cyclisme ?")
- **1** : Question spécifique (ex: "Comment choisir un vélo de route ?")
- **2** : Question très spécifique/sous-question (ex: "Quelle taille de cadre pour un vélo de route si je mesure 1m75 ?")

FORMAT DE SORTIE : JSON uniquement
{{
    "user_intent": "Informational|Commercial|Transactional|Navigational",
    "persona": "un des personas définis ou Non défini",
    "product_service": "un des produits définis ou Autre",
    "brand_mentioned": true|false,
    "fan_out_level": 0|1|2
}}"""


def classify_questions_batch(client, questions: List[str], classification_prompt: str, 
                             progress_callback=None, batch_size: int = 5) -> List[Dict]:
    """Classifie un batch de questions via GPT"""
    results = []
    total = len(questions)
    
    for i in range(0, total, batch_size):
        batch = questions[i:i+batch_size]
        batch_results = []
        
        for j, question in enumerate(batch):
            if progress_callback:
                progress_callback((i + j) / total, f"Classification: {i+j+1}/{total}")
            
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": classification_prompt},
                        {"role": "user", "content": f"Question à classifier:\n\n{question}"}
                    ],
                    temperature=0.2,
                    max_tokens=200
                )
                
                content = response.choices[0].message.content.strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                classification = json.loads(content)
                batch_results.append(classification)
                
            except Exception as e:
                # Valeurs par défaut en cas d'erreur
                batch_results.append({
                    "user_intent": "Informational",
                    "persona": "Non défini",
                    "product_service": "Autre",
                    "brand_mentioned": False,
                    "fan_out_level": 1,
                    "error": str(e)
                })
        
        results.extend(batch_results)
        time.sleep(0.1)  # Rate limiting léger
    
    return results


def get_central_question(embeddings_array: np.ndarray, questions: List[str], indices: List[int]) -> str:
    """Trouve la question la plus centrale (proche du centroïde) dans un cluster"""
    if len(indices) == 1:
        return questions[indices[0]]
    
    cluster_embeddings = embeddings_array[indices]
    centroid = cluster_embeddings.mean(axis=0)
    
    # Distance de chaque question au centroïde
    distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
    central_idx = indices[np.argmin(distances)]
    
    return questions[central_idx]


def run_clustering(
    input_file,
    openai_api_key: str,
    similarity_threshold: float,
    use_hdbscan: bool = True,
    min_cluster_size: int = 3,
    brand_name: str = "",
    personas_input: str = "",
    products_services_input: str = "",
    progress=gr.Progress()
):
    """Étape 3 : Embeddings & Clustering + Classification multi-dimensionnelle
    
    Améliorations v3:
    - HDBSCAN pour détection naturelle des clusters + bruit
    - Représentant par centralité (pas plus courte)
    - Flag is_geo_relevant (clusters >= min_cluster_size)
    - Classification GPT: user_intent, persona, product_service, brand_mentioned, fan_out_level
    """
    logs = []
    
    if not OPENAI_AVAILABLE:
        return None, None, "❌ OpenAI non installé"
    
    if not input_file:
        return None, None, "❌ Veuillez uploader un fichier CSV"
    
    api_key = openai_api_key or os.getenv("OPENAI_SECRET_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, None, "❌ Clé API OpenAI non trouvée"
    
    try:
        logs.append("="*50)
        logs.append("🧠 EMBEDDINGS & CLUSTERING v2")
        logs.append("="*50)
        
        # Charger
        progress(0.05, desc="Chargement...")
        df = pd.read_csv(input_file.name)
        initial_count = len(df)
        logs.append(f"📂 {initial_count} questions chargées")
        
        # Détecter la colonne de questions
        text_col = 'title' if 'title' in df.columns else 'raw_text' if 'raw_text' in df.columns else None
        if not text_col:
            return None, None, "❌ Colonne 'title' ou 'raw_text' non trouvée"
        logs.append(f"   Colonne utilisée: '{text_col}'")
        
        # ========== EMBEDDINGS ==========
        logs.append("")
        logs.append("🔢 Calcul des embeddings (text-embedding-3-small)...")
        progress(0.2, desc="Embeddings...")
        
        client = OpenAI(api_key=api_key)
        questions = df[text_col].fillna("").astype(str).tolist()
        questions_clean = [normalize_text_formal(q) for q in questions]
        
        embeddings = get_embeddings_batch(client, questions_clean)
        embeddings_array = np.array(embeddings, dtype=float)
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings_array = embeddings_array / norms
        logs.append(f"   ✅ {len(embeddings)} embeddings calculés")
        
        # ========== CLUSTERING ==========
        logs.append("")
        n_noise = 0
        
        # Essayer HDBSCAN si disponible et demandé
        if use_hdbscan and HDBSCAN_AVAILABLE and len(embeddings) > 10:
            logs.append("🎯 Clustering HDBSCAN (détection bruit + clusters naturels)...")
            progress(0.5, desc="HDBSCAN...")
            
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=min_cluster_size,
                min_samples=2,
                metric='euclidean',
                cluster_selection_method='eom'
            )
            labels = clusterer.fit_predict(embeddings_array)
            
            # -1 = bruit
            n_noise = (labels == -1).sum()
            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
            
            # Formater les labels
            df['cluster_id'] = [f"C{label:03d}" if label >= 0 else "NOISE" for label in labels]
            df['is_noise'] = labels == -1
            
            logs.append(f"   ✅ {n_clusters} clusters identifiés")
            logs.append(f"   🔇 {n_noise} questions classées comme bruit ({100*n_noise/len(df):.1f}%)")

            if n_clusters < 5 and SKLEARN_AVAILABLE and len(embeddings) > 1:
                logs.append(f"   ⚠️ HDBSCAN a produit seulement {n_clusters} clusters → fallback Agglomératif")
                similarity_matrix = cosine_similarity(embeddings_array)
                distance_matrix = 1 - similarity_matrix

                clustering = AgglomerativeClustering(
                    n_clusters=None,
                    distance_threshold=1 - similarity_threshold,
                    metric='precomputed',
                    linkage='average'
                )
                labels = clustering.fit_predict(distance_matrix)
                df['cluster_id'] = [f"C{label:03d}" for label in labels]
                df['is_noise'] = False
                n_clusters = len(set(labels))
                n_noise = 0
                logs.append(f"   ✅ {n_clusters} clusters identifiés (fallback)")
            
        elif SKLEARN_AVAILABLE and len(embeddings) > 1:
            logs.append("🎯 Clustering Agglomératif (fallback)...")
            progress(0.5, desc="Clustering...")
            
            similarity_matrix = cosine_similarity(embeddings_array)
            distance_matrix = 1 - similarity_matrix
            
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=1 - similarity_threshold,
                metric='precomputed',
                linkage='average'
            )
            labels = clustering.fit_predict(distance_matrix)
            df['cluster_id'] = [f"C{label:03d}" for label in labels]
            df['is_noise'] = False
            n_clusters = len(set(labels))
            logs.append(f"   ✅ {n_clusters} clusters identifiés")
            logs.append(f"   ⚠️ HDBSCAN non disponible, pas de détection de bruit")
        else:
            df['cluster_id'] = [f"C{i:03d}" for i in range(len(df))]
            df['is_noise'] = False
            logs.append("   ⚠️ Aucun clustering disponible")
            n_clusters = len(df)
        
        # ========== CRÉER TABLE CLUSTERS ==========
        logs.append("")
        logs.append("📊 Analyse des clusters...")
        progress(0.6, desc="Analyse clusters...")
        
        clusters_data = []
        valid_clusters = [c for c in df['cluster_id'].unique() if c != "NOISE"]
        representatives_for_classification = []
        
        for cluster_id in valid_clusters:
            cluster_mask = df['cluster_id'] == cluster_id
            cluster_df = df[cluster_mask]
            cluster_indices = cluster_mask[cluster_mask].index.tolist()
            
            # Sources dans ce cluster
            sources = []
            if 'platform' in cluster_df.columns:
                sources = cluster_df['platform'].dropna().unique().tolist()
            elif 'source_type' in cluster_df.columns:
                sources = cluster_df['source_type'].dropna().unique().tolist()
            
            # Question représentative par CENTRALITÉ (pas plus courte)
            questions_in_cluster = cluster_df[text_col].tolist()
            representative = get_central_question(
                embeddings_array, 
                questions_clean, 
                [df.index.get_loc(i) for i in cluster_df.index]
            )
            representatives_for_classification.append(representative)
            
            # Flag GEO relevant
            nb_questions = len(cluster_df)
            is_geo_relevant = (
                nb_questions >= min_cluster_size and  # Assez de questions
                len(sources) >= 1  # Au moins une source identifiée
            )
            
            # Générer un intent_label à partir de la question représentative
            # Format: mots clés en snake_case (max 5 mots)
            intent_label = generate_intent_label(representative)
            
            clusters_data.append({
                'cluster_id': cluster_id,
                'intent_label': intent_label,
                'nb_questions': nb_questions,
                'sources': ', '.join(sources) if sources else 'unknown',
                'nb_sources': len(sources),
                'question_representative': representative,
                'is_geo_relevant': is_geo_relevant,
                'all_questions': ' | '.join(questions_in_cluster[:5])
            })
        
        clusters_df = pd.DataFrame(clusters_data)
        clusters_df = clusters_df.sort_values('nb_questions', ascending=False)

        logs.append("")
        logs.append("ℹ️ Classification ignorée (mode clustering simple)")
        clusters_df['user_intent'] = 'Non classifié'
        clusters_df['persona'] = 'Non défini'
        clusters_df['product_service'] = 'Autre'
        clusters_df['brand_mentioned'] = False
        clusters_df['fan_out_level'] = 1
        
        # Stats
        geo_relevant = clusters_df['is_geo_relevant'].sum()
        not_relevant = len(clusters_df) - geo_relevant
        
        # ========== STATS PAR CLUSTER ==========
        logs.append("")
        logs.append("📊 Top 10 clusters:")
        for _, row in clusters_df.head(10).iterrows():
            flag = "✅" if row['is_geo_relevant'] else "⚠️"
            q_short = row['question_representative'][:55] + "..." if len(row['question_representative']) > 55 else row['question_representative']
            logs.append(f"   {flag} {row['cluster_id']}: {row['nb_questions']} q. - \"{q_short}\"")
        
        if len(clusters_df) > 10:
            logs.append(f"   ... et {len(clusters_df) - 10} autres clusters")
        
        # ========== EXPORT ==========
        progress(0.9, desc="Export...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Export 1: Questions avec cluster_id
        questions_output = EXPORTS_DIR / f"etape3_questions_avec_clusters_{timestamp}.csv"
        df.to_csv(questions_output, index=False)
        
        # Export 2: Table des clusters
        clusters_output = EXPORTS_DIR / f"etape3_clusters_intentions_{timestamp}.csv"
        clusters_df.to_csv(clusters_output, index=False)
        
        questions_output = str(questions_output)
        clusters_output = str(clusters_output)
        
        # Résumé
        logs.append("")
        logs.append("="*50)
        logs.append("📊 RÉSUMÉ")
        logs.append("="*50)
        logs.append(f"   Questions en entrée: {initial_count}")
        logs.append(f"   Questions clusterisées: {initial_count - n_noise}")
        if n_noise > 0:
            logs.append(f"   Questions bruit (NOISE): {n_noise}")
        logs.append(f"   Clusters créés: {len(clusters_df)}")
        logs.append(f"   ✅ Clusters GEO-relevant: {geo_relevant}")
        logs.append(f"   ⚠️ Clusters non-exploitables: {not_relevant}")
        logs.append("")
        logs.append("📁 EXPORTS:")
        logs.append("   1. CSV Questions (toutes questions + cluster_id + is_noise)")
        logs.append("   2. CSV Clusters (avec is_geo_relevant)")
        logs.append("")
        logs.append("✅ Clustering terminé!")
        logs.append("")
        logs.append("👉 Prochaine étape: Générer des prompts GEO (Onglet 4)")
        logs.append("   💡 Filtrer sur is_geo_relevant=True pour les clusters exploitables")
        
        return questions_output, clusters_output, "\n".join(logs)
        
    except Exception as e:
        import traceback
        return None, None, f"❌ Erreur: {str(e)}\n\n{traceback.format_exc()}"


# ============================================
# ÉTAPE 4: GÉNÉRATION DE PROMPTS GEO
# ============================================

PROMPT_GENERATION_SYSTEM = """Tu es un expert en GEO (Generative Engine Optimization).

MISSION : Reformuler les VRAIES questions utilisateurs fournies en prompts testables pour ChatGPT/Perplexity/Claude.

⚠️ RÈGLE CRITIQUE #1 : Tu dois UNIQUEMENT reformuler les questions fournies. NE PAS inventer de nouvelles questions ou sujets.

⚠️ RÈGLE CRITIQUE #2 : Tu DOIS générer les prompts dans LA MÊME LANGUE que les questions fournies.
- Si les questions sont en néerlandais → génère en néerlandais
- Si les questions sont en français → génère en français  
- Si les questions sont en anglais → génère en anglais

OBJECTIF : Ces prompts serviront à tester si une marque apparaît naturellement dans les réponses des moteurs génératifs.

PROCESSUS :
1. Lis attentivement la question représentative ET les exemples de questions du cluster
2. DÉTECTE LA LANGUE des questions fournies
3. Identifie l'INTENTION commune de ces questions
4. Reformule ces questions existantes en 5-10 variantes conversationnelles DANS LA MÊME LANGUE
5. Garde le MÊME SUJET et la MÊME INTENTION - ne dévie pas

CRITÈRES pour les reformulations :
1. Langage naturel conversationnel (comme un utilisateur parlerait à ChatGPT)
2. Neutres (sans mentionner de marque)
3. BASÉES sur les questions originales fournies
4. Variantes de formulation : question directe, demande de conseil, comparaison, recommandation
5. MÊME LANGUE que les questions originales

FORMAT JSON :
{
    "intent_label": "label court de l'intention (basé sur les questions fournies)",
    "prompts": [
        {"prompt": "reformulation de la question originale", "type": "information|conseil|comparaison|recommandation"},
        ...
    ]
}"""


def generate_prompts_for_cluster(client, cluster_data: Dict) -> Dict:
    """Génère 5-10 prompts GEO pour un cluster"""
    cluster_id = cluster_data.get('cluster_id', '')
    # Support both old and new column names
    representative = cluster_data.get('question_representative', '') or cluster_data.get('canonical_question', '')
    all_questions = cluster_data.get('all_questions', '')
    intent_label = cluster_data.get('intent_label', '')
    
    # Nouvelles dimensions de classification
    user_intent = cluster_data.get('user_intent', 'Non classifié')
    persona = cluster_data.get('persona', 'Non défini')
    product_service = cluster_data.get('product_service', 'Autre')
    brand_mentioned = cluster_data.get('brand_mentioned', False)
    fan_out_level = cluster_data.get('fan_out_level', 1)
    
    # Construire le contexte de classification
    classification_context = f"""
CLASSIFICATION DU CLUSTER:
- User Intent: {user_intent}
- Persona: {persona}
- Produit/Service: {product_service}
- Marque mentionnée: {'Oui' if brand_mentioned else 'Non'}
- Fan-Out Level: {fan_out_level} (0=générique, 1=spécifique, 2=très spécifique)
"""
    
    user_prompt = f"""CLUSTER: {cluster_id}
INTENTION: {intent_label}
{classification_context}
QUESTION REPRÉSENTATIVE (la plus centrale du cluster):
"{representative}"

AUTRES QUESTIONS RÉELLES DE CE CLUSTER:
{all_questions}

⚠️ RAPPEL: Reformule UNIQUEMENT ces questions ci-dessus. Ne change pas de sujet. Génère 5-10 variantes conversationnelles de ces MÊMES questions.
💡 Tiens compte de la classification ci-dessus pour adapter le ton et le style des reformulations."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PROMPT_GENERATION_SYSTEM},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.4,
            max_tokens=800
        )
        content = response.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
        result['cluster_id'] = cluster_id
        return result
    except Exception as e:
        return {
            'cluster_id': cluster_id,
            'intent_label': representative[:50] if representative else cluster_id,
            'prompts': [{'prompt': representative, 'type': 'information'}],
            'error': str(e)
        }


def run_prompt_generation(
    input_file,
    openai_api_key: str,
    max_clusters: int,
    progress=gr.Progress()
):
    """Génère des prompts GEO à partir des clusters"""
    logs = []
    
    if not OPENAI_AVAILABLE:
        return None, None, "❌ OpenAI non installé"
    
    if not input_file:
        return None, None, "❌ Veuillez uploader le CSV des clusters (sortie de l'étape 3)"
    
    api_key = openai_api_key or os.getenv("OPENAI_SECRET_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, None, "❌ Clé API OpenAI non trouvée"
    
    try:
        logs.append("="*50)
        logs.append("🎯 GÉNÉRATION DE PROMPTS GEO")
        logs.append("="*50)
        
        # Charger les clusters
        progress(0.05, desc="Chargement...")
        df = pd.read_csv(input_file.name)
        logs.append(f"📂 {len(df)} clusters chargés")
        
        # Limiter le nombre de clusters
        if len(df) > max_clusters:
            df = df.head(max_clusters)
            logs.append(f"   ⚠️ Limité aux {max_clusters} premiers clusters")
        
        # Initialiser OpenAI
        client = OpenAI(api_key=api_key)
        logs.append("🔑 Connexion OpenAI OK")
        
        # Générer les prompts pour chaque cluster
        logs.append("")
        logs.append("🤖 Génération des prompts...")
        
        all_prompts = []
        all_results = []
        
        for idx, row in df.iterrows():
            progress(0.1 + 0.8 * idx / len(df), desc=f"Cluster {idx+1}/{len(df)}...")
            
            cluster_data = row.to_dict()
            result = generate_prompts_for_cluster(client, cluster_data)
            all_results.append(result)
            
            # Extraire les prompts
            cluster_id = result.get('cluster_id', f'C{idx}')
            intent_label = result.get('intent_label', '')
            
            for p in result.get('prompts', []):
                all_prompts.append({
                    'cluster_id': cluster_id,
                    'intent_label': intent_label,
                    'prompt': p.get('prompt', ''),
                    'prompt_type': p.get('type', 'information')
                })
            
            logs.append(f"   [{idx+1}/{len(df)}] {cluster_id}: {len(result.get('prompts', []))} prompts")
            time.sleep(0.3)
        
        # Créer les DataFrames
        prompts_df = pd.DataFrame(all_prompts)
        
        # Export
        progress(0.95, desc="Export...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Export prompts (format plat)
        prompts_output = EXPORTS_DIR / f"etape4_prompts_geo_{timestamp}.csv"
        prompts_df.to_csv(prompts_output, index=False)
        
        # Export JSON complet (avec structure)
        json_output = EXPORTS_DIR / f"etape4_prompts_geo_{timestamp}.json"
        with open(json_output, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        
        prompts_output = str(prompts_output)
        json_output = str(json_output)
        
        # Résumé
        logs.append("")
        logs.append("="*50)
        logs.append("📊 RÉSUMÉ")
        logs.append("="*50)
        logs.append(f"   Clusters traités: {len(df)}")
        logs.append(f"   Prompts générés: {len(prompts_df)}")
        logs.append(f"   Moyenne par cluster: {len(prompts_df)/len(df):.1f}")
        
        if 'prompt_type' in prompts_df.columns:
            logs.append("")
            logs.append("   Distribution par type:")
            for ptype, count in prompts_df['prompt_type'].value_counts().items():
                logs.append(f"      - {ptype}: {count}")
        
        logs.append("")
        logs.append("📁 EXPORTS:")
        logs.append("   1. CSV Prompts (format plat pour monitoring)")
        logs.append("   2. JSON Complet (structure par cluster)")
        logs.append("")
        logs.append("✅ Génération terminée!")
        logs.append("")
        logs.append("👉 Prochaine étape: Tester ces prompts dans ChatGPT/Perplexity (Étape 5)")
        
        return prompts_output, json_output, "\n".join(logs)
        
    except Exception as e:
        import traceback
        return None, None, f"❌ Erreur: {str(e)}\n\n{traceback.format_exc()}"


# ============================================
# INTERFACE GRADIO
# ============================================

# Import du thème (optionnel - fallback si non disponible)
try:
    from brand_theme import apply_theme
    THEME = apply_theme(
        title="Prompt Finder",
        subtitle="Pipeline GEO Complet - Collecte, Transformation, Clustering, Prompts"
    )
    BRAND_CSS = THEME['css']
    BRAND_HEADER = THEME['header']
    BRAND_FOOTER = THEME['footer']
except ImportError:
    BRAND_CSS = ""
    BRAND_HEADER = ""
    BRAND_FOOTER = ""

with gr.Blocks(title="Prompt Finder", css=BRAND_CSS) as app:
    
    # Header Semactic avec logo image
    gr.HTML("""
    <div style="padding: 0 0 1.5rem 0; border-bottom: 1px solid #E8E4DC; margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">
            <img src="file/logo_semactic.jpeg" alt="Semactic" style="height: 40px; width: auto; border-radius: 8px;" onerror="this.style.display='none'">
        </div>
        <h1 style="font-size: 1.25rem; font-weight: 600; color: #1F2937; margin: 0.5rem 0 0.25rem 0;">Prompt Finder</h1>
        <p style="color: #6B7280; font-size: 0.9rem; margin: 0;">Pipeline GEO Complet - Collecte, Transformation, Clustering, Prompts</p>
    </div>
    """)
    
    with gr.Accordion("Comment ça marche ?", open=False):
        gr.Markdown("""
        **Étape 1 - Collecte** : Récupérez des données depuis Reddit, Forums, Trustpilot, Google PAA et **Google Search Console**  
        **Étape 2 - Transformation** : Convertissez les contenus forums en questions exploitables  
        **Étape 3 - Clustering** : Regroupez les questions par intention sémantique  
        **Étape 4 - Prompts GEO** : Générez 5-10 prompts testables par cluster
        
        ---
        
        **💡 Astuce GSC** : Pour extraire les queries conversationnelles (10+ mots) depuis Google Search Console :
        1. Allez dans GSC → Performance → Ajouter filtre → Query → Regex personnalisée
        2. Utilisez ce regex : `^(?:\S+\s+){9,}\S+$`
        3. Exportez le CSV et uploadez-le dans l'onglet "GSC Conversations" ci-dessous
        """)
    
    with gr.Tabs():
        # ========== ONGLET 1 : COLLECTE ==========
        with gr.TabItem("Étape 1 : Collecte"):
            with gr.Row():
                with gr.Column(scale=1, elem_classes="sem-card"):
                    gr.Markdown("## Configuration")
                    
                    client_name = gr.Textbox(
                        label="Nom du client",
                        placeholder="Ex: Decathlon"
                    )
                    
                    gr.Markdown("### Fichier Keywords")
                    keywords_file = gr.File(
                        label="Upload Excel/CSV (colonne 'keywords')",
                        file_types=[".xlsx", ".xls", ".csv"]
                    )
                    keywords_preview = gr.Markdown("*Uploadez un fichier pour voir l'aperçu*")
                    
                    max_keywords = gr.Slider(
                        minimum=1, maximum=500, value=50, step=5,
                        label="Limite de keywords"
                    )
                
                with gr.Column(scale=2, elem_classes="sem-card"):
                    gr.Markdown("## Sources")
                    
                    with gr.Tabs():
                        with gr.TabItem("Reddit"):
                            enable_reddit = gr.Checkbox(label="Activer Reddit", value=True)
                            subreddits = gr.Textbox(
                                label="Subreddits (séparés par virgule)",
                                placeholder="Ex: running, cycling, france",
                                lines=2
                            )
                            max_posts_per_subreddit = gr.Slider(
                                minimum=10, maximum=200, value=50, step=10,
                                label="Max posts par subreddit"
                            )
                        
                        with gr.TabItem("Forums"):
                            enable_forums = gr.Checkbox(label="Activer Forums", value=False)
                            forums = gr.Textbox(
                                label="Forums (format: nom|url)",
                                placeholder="forum1|https://example.com/forum",
                                lines=4
                            )
                            max_results_per_forum = gr.Slider(
                                minimum=10, maximum=100, value=30, step=5,
                                label="Max résultats par forum"
                            )
                        
                        with gr.TabItem("Trustpilot"):
                            enable_trustpilot = gr.Checkbox(label="Activer Trustpilot", value=True)
                            trustpilot_url = gr.Textbox(
                                label="URL Trustpilot",
                                placeholder="https://fr.trustpilot.com/review/www.example.com"
                            )
                            max_trustpilot_pages = gr.Slider(
                                minimum=1, maximum=20, value=5, step=1,
                                label="Nombre de pages"
                            )
                        
                        with gr.TabItem("SERP/PAA"):
                            enable_serp = gr.Checkbox(label="Activer SERP/PAA", value=True)
                            max_serp_results = gr.Slider(
                                minimum=0, maximum=1000, value=30, step=10,
                                label="Max requêtes SERP"
                            )
                            gr.Markdown("Requiert `DATAFORSEO_LOGIN` et `DATAFORSEO_PASSWORD`")
                        
                        with gr.TabItem("GSC Conversations"):
                            enable_gsc = gr.Checkbox(label="Activer GSC Conversations", value=False)
                            gsc_file = gr.File(
                                label="Export CSV de Google Search Console",
                                file_types=[".csv"]
                            )
                            min_words_gsc = gr.Slider(
                                minimum=5, maximum=20, value=10, step=1,
                                label="Minimum de mots par query"
                            )
                            gr.Markdown("""
                            **Comment obtenir ce fichier :**
                            1. GSC → Performance → Filtre Query → Regex : `^(?:\\S+\\s+){9,}\\S+$`
                            2. Exporter en CSV
                            """)
                
                with gr.Column(scale=1, elem_classes="sem-card"):
                    gr.Markdown("## Région")
                    language_region = gr.Radio(
                        choices=["FR - Français", "NL - Néerlandais", "EN - Anglais"],
                        value="FR - Français",
                        label="Langue d'analyse"
                    )
            
            gr.Markdown("---")
            
            with gr.Row():
                run_btn = gr.Button("Lancer la collecte", variant="primary", size="lg")
            
            with gr.Row():
                with gr.Column():
                    output_logs = gr.Textbox(label="Logs", lines=20, interactive=False)
                with gr.Column():
                    output_file = gr.File(label="Fichier CSV (pour Étape 2)")
            
            keywords_file.change(fn=preview_keywords, inputs=[keywords_file], outputs=[keywords_preview])
            
            run_btn.click(
                fn=run_scraping,
                inputs=[
                    client_name, keywords_file, max_keywords,
                    subreddits, forums, trustpilot_url,
                    max_posts_per_subreddit, max_results_per_forum,
                    max_trustpilot_pages, max_serp_results,
                    enable_reddit, enable_forums, enable_trustpilot, enable_serp,
                    language_region,
                    enable_gsc, gsc_file, min_words_gsc
                ],
                outputs=[output_file, output_logs]
            )
        
        # ========== ONGLET 2 : TRANSFORMATION ==========
        with gr.TabItem("Étape 2 : Transformation"):
            gr.Markdown("## Transformation → Questions GEO")
            gr.Markdown("Convertit les contenus forums en questions exploitables via GPT-4o-mini.")
            
            with gr.Accordion("En savoir plus", open=False):
                gr.Markdown("""
                Cette étape prend le CSV de l'étape 1 et :
                1. **Conserve** les questions PAA de DataForSEO (inchangées)
                2. **Transforme** les contenus Reddit/Forums en questions exploitables via GPT-4o-mini
                
                Le résultat est un CSV contenant uniquement des questions prêtes pour l'analyse GEO.
                
                ---
                
                **Entrée** : CSV avec colonnes `source_type`, `is_question`, `raw_text`...
                
                **Traitement** :
                - Questions PAA (`is_question=True`) → conservées telles quelles
                - Contenus forums (`is_question=False`) → transformés en 1-3 questions
                
                **Sortie** : CSV avec uniquement des questions
                
                **Coût estimé** : ~$0.01 pour 100 contenus transformés (GPT-4o-mini)
                """)
            
            with gr.Row():
                with gr.Column(elem_classes="sem-card"):
                    transform_input = gr.File(
                        label="CSV de l'étape 1",
                        file_types=[".csv"]
                    )
                    transform_language = gr.Radio(
                        choices=["FR - Français", "NL - Néerlandais", "EN - Anglais"],
                        value="FR - Français",
                        label="Langue de génération des questions"
                    )
                    gr.Markdown("*Utilise `OPENAI_SECRET_KEY` configuré dans les Secrets HF.*")
            
            with gr.Row():
                transform_btn = gr.Button("Lancer la transformation", variant="primary", size="lg")
            
            with gr.Row():
                with gr.Column():
                    transform_logs = gr.Textbox(label="Logs", lines=20, interactive=False)
                with gr.Column():
                    transform_output = gr.File(label="CSV Questions GEO")
            
            transform_btn.click(
                fn=lambda f, lang: run_transformation(f, None, lang),
                inputs=[transform_input, transform_language],
                outputs=[transform_output, transform_logs]
            )
        
        # ========== ONGLET 3 : CLUSTERING ==========
        with gr.TabItem("Étape 3 : Clustering"):
            gr.Markdown("## Clustering par intention")
            gr.Markdown("Regroupe les questions similaires en clusters sémantiques via embeddings OpenAI.")
            
            with gr.Accordion("En savoir plus", open=False):
                gr.Markdown("""
                Cette étape prend le CSV de l'étape 2 (questions) et :
                
                1. **Vectorise** chaque question via OpenAI embeddings (text-embedding-3-small)
                2. **Regroupe** les questions similaires en clusters (= intentions GEO)
                3. **Détecte le bruit** : questions marginales/hors-scope (HDBSCAN)
                4. **Évalue la pertinence GEO** de chaque cluster
                
                **Améliorations v2** :
                - HDBSCAN : clusters naturels + détection du bruit
                - Représentant par centralité (pas juste la plus courte)
                - Flag `is_geo_relevant` pour filtrer les clusters exploitables
                
                ---
                
                **CSV Questions** (`*_questions_clustered.csv`) :
                - Toutes vos questions originales
                - `cluster_id` (C001, C002... ou NOISE)
                - `is_noise` (True/False)
                
                **CSV Clusters** (`*_clusters.csv`) :
                - 1 ligne par cluster/intention
                - `question_representative` (par centralité)
                - `is_geo_relevant` (exploitable pour GEO)
                - `nb_questions`, `sources`
                
                **Coût** : ~$0.01 pour 500 questions
                
                **Prérequis** : `pip install hdbscan` pour HDBSCAN
                """)
            
            with gr.Row():
                with gr.Column(elem_classes="sem-card"):
                    clustering_input = gr.File(
                        label="CSV de l'étape 2 (questions)",
                        file_types=[".csv"]
                    )
                    
                    gr.Markdown("### Paramètres HDBSCAN")
                    
                    use_hdbscan = gr.Checkbox(
                        label="HDBSCAN (recommandé)",
                        value=True
                    )
                    
                    min_cluster_size = gr.Slider(
                        minimum=2, maximum=10, value=3, step=1,
                        label="Taille min. cluster"
                    )
                    
                    similarity_threshold = gr.Slider(
                        minimum=0.70, maximum=0.95, value=0.85, step=0.05,
                        label="Seuil similarité (si HDBSCAN désactivé)"
                    )
                    
                    gr.Markdown("*Utilise `OPENAI_SECRET_KEY` configuré dans les Secrets HF.*")
            
            with gr.Row():
                clustering_btn = gr.Button("Lancer le clustering", variant="primary", size="lg")
            
            with gr.Row():
                with gr.Column():
                    clustering_logs = gr.Textbox(label="Logs", lines=20, interactive=False)
                with gr.Column():
                    clustering_questions_output = gr.File(label="CSV Questions (avec cluster_id)", visible=False)
                    clustering_clusters_output = gr.File(label="CSV Clusters (1 par intention)")
            
            clustering_btn.click(
                fn=lambda f, t, h, m: run_clustering(
                    f, None, t, h, m, "", "", ""
                ),
                inputs=[
                    clustering_input, similarity_threshold, use_hdbscan, min_cluster_size,
                ],
                outputs=[clustering_questions_output, clustering_clusters_output, clustering_logs]
            )
        
        # ========== ONGLET 4 : GÉNÉRATION PROMPTS GEO ==========
        with gr.TabItem("Étape 4 : Prompts GEO"):
            gr.Markdown("## Génération de Prompts GEO")
            gr.Markdown("Génère 5-10 prompts testables par cluster pour ChatGPT, Perplexity, Claude, Gemini.")
            
            with gr.Accordion("En savoir plus", open=False):
                gr.Markdown("""
                Cette étape prend le **CSV des clusters** (sortie de l'étape 3) et génère **5-10 prompts** par cluster.
                
                Ces prompts sont :
                - **Neutres** (sans marque) pour tester si votre marque émerge naturellement
                - **Variés** : informationnels, conseils, comparaisons, recommandations
                - **Prêts à tester** dans ChatGPT, Perplexity, Claude, Gemini
                
                **Objectif** : Constituer une banque de prompts pour le monitoring GEO (Étape 5)
                
                ---
                
                **Types de prompts générés** pour chaque cluster/intention :
                
                - **Information** : "Qu'est-ce que..." / "Comment fonctionne..."
                - **Conseil** : "Que me conseilles-tu pour..." / "Quel est le meilleur..."
                - **Comparaison** : "Quelles différences entre..."
                - **Recommandation** : "Peux-tu me recommander..."
                
                **Coût estimé** : ~$0.02 pour 50 clusters (GPT-4o-mini)
                """)
            
            with gr.Row():
                with gr.Column(elem_classes="sem-card"):
                    prompts_input = gr.File(
                        label="CSV Clusters (sortie Étape 3)",
                        file_types=[".csv"]
                    )
                    
                    max_clusters_slider = gr.Slider(
                        minimum=5, maximum=200, value=50, step=5,
                        label="Nombre max de clusters"
                    )
                    
                    gr.Markdown("*Utilise `OPENAI_SECRET_KEY` configuré dans les Secrets HF.*")
            
            with gr.Row():
                prompts_btn = gr.Button("Générer les prompts", variant="primary", size="lg")
            
            with gr.Row():
                with gr.Column():
                    prompts_logs = gr.Textbox(label="Logs", lines=20, interactive=False)
                with gr.Column():
                    prompts_csv_output = gr.File(label="CSV Prompts (format plat)")
                    prompts_json_output = gr.File(label="JSON Complet (par cluster)")
            
            prompts_btn.click(
                fn=lambda f, m: run_prompt_generation(f, None, m),
                inputs=[prompts_input, max_clusters_slider],
                outputs=[prompts_csv_output, prompts_json_output, prompts_logs]
            )
    
    # Footer avec branding (si disponible)
    if BRAND_FOOTER:
        gr.HTML(BRAND_FOOTER)


if __name__ == "__main__":
    app.queue().launch()
