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


# ============================================
# MODELS
# ============================================

class SourceType(Enum):
    FORUM = "forum"
    REVIEW = "review"
    SERP = "serp"
    QA = "qa"


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
    min_text_length: int = 30
    max_text_length: int = 10000
    delay_between_requests: float = 2.0


# ============================================
# REDDIT SCRAPER
# ============================================

def scrape_reddit(config: SimpleConfig, logs: List[str]) -> List[RawItem]:
    """Scrape Reddit via API JSON publique"""
    items = []
    headers = {"User-Agent": "PromptFinder/1.0 (Question scraper for GEO analysis)"}
    
    for subreddit in config.subreddits:
        for keyword in config.keywords[:10]:  # Limiter pour éviter rate limit
            try:
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {
                    "q": keyword,
                    "restrict_sr": "on",
                    "sort": "relevance",
                    "t": "year",
                    "limit": min(config.max_posts_per_subreddit // len(config.keywords[:10]), 25)
                }
                
                time.sleep(config.delay_between_requests)
                response = requests.get(url, params=params, headers=headers, timeout=30)
                
                if response.status_code == 429:
                    logs.append(f"   ⚠️ Rate limit Reddit, pause 60s...")
                    time.sleep(60)
                    response = requests.get(url, params=params, headers=headers, timeout=30)
                
                if response.status_code != 200:
                    continue
                
                data = response.json()
                posts = data.get("data", {}).get("children", [])
                
                for post_data in posts:
                    post = post_data.get("data", {})
                    title = post.get("title", "")
                    selftext = post.get("selftext", "")
                    full_text = f"{title}\n\n{selftext}".strip()
                    
                    if len(full_text) >= 20:
                        item = RawItem(
                            source_type=SourceType.FORUM,
                            platform="reddit",
                            raw_text=full_text,
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            title=title,
                            date=datetime.fromtimestamp(post.get("created_utc", 0)) if post.get("created_utc") else None,
                            metadata={
                                "subreddit": subreddit,
                                "score": post.get("score", 0),
                                "search_term": keyword
                            },
                            client_slug=config.client_slug
                        )
                        items.append(item)
                
            except Exception as e:
                logs.append(f"   ⚠️ Erreur r/{subreddit}: {str(e)[:50]}")
    
    return items


# ============================================
# TRUSTPILOT SCRAPER
# ============================================

def scrape_trustpilot(config: SimpleConfig, logs: List[str]) -> List[RawItem]:
    """Scrape Trustpilot via HTML"""
    items = []
    
    if not config.trustpilot_url:
        return items
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    for page in range(1, config.max_trustpilot_pages + 1):
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
                    # Titre
                    title_el = card.select_one("h2, [data-service-review-title-typography]")
                    title = title_el.get_text(strip=True) if title_el else ""
                    
                    # Contenu
                    content_el = card.select_one("p[data-service-review-text-typography], .review-content")
                    content = content_el.get_text(strip=True) if content_el else ""
                    
                    # Rating
                    rating = None
                    rating_el = card.select_one("[data-service-review-rating], .star-rating")
                    if rating_el:
                        rating_img = rating_el.select_one("img")
                        if rating_img and rating_img.get("alt"):
                            match = re.search(r"(\d)", rating_img.get("alt", ""))
                            if match:
                                rating = float(match.group(1))
                    
                    # Date
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
# SERP/PAA SCRAPER (DataForSEO)
# ============================================

def scrape_serp(config: SimpleConfig, logs: List[str]) -> List[RawItem]:
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
    
    for keyword in config.keywords[:config.max_serp_results]:
        try:
            payload = [{
                "keyword": keyword,
                "location_code": 2250,  # France
                "language_code": "fr",
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
# QUALITY FILTER
# ============================================

def filter_items(items: List[RawItem], config: SimpleConfig) -> Tuple[List[RawItem], int]:
    """Filtre les items par qualité"""
    accepted = []
    seen_hashes = set()
    rejected_count = 0
    
    for item in items:
        text = item.raw_text
        
        # Longueur
        if len(text) < config.min_text_length or len(text) > config.max_text_length:
            rejected_count += 1
            continue
        
        # Doublons
        text_hash = hashlib.md5(text.lower().encode()).hexdigest()
        if text_hash in seen_hashes:
            rejected_count += 1
            continue
        seen_hashes.add(text_hash)
        
        # Spam
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
    temp_dir = tempfile.mkdtemp()
    output_path = os.path.join(temp_dir, filename)
    
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
    
    return output_path


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
    progress=gr.Progress()
):
    """Exécute le scraping"""
    
    if not client_name:
        return None, "❌ Veuillez entrer un nom de client."
    
    keywords = parse_keywords_file(keywords_file)
    if not keywords:
        return None, "❌ Veuillez uploader un fichier Excel/CSV avec une colonne 'keywords'."
    
    # Limiter keywords
    keywords = keywords[:max_keywords]
    
    # Parser subreddits
    subreddit_list = [s.strip() for s in subreddits.split(",") if s.strip()] if enable_reddit else []
    
    # Parser forums
    forum_list = []
    if enable_forums and forums.strip():
        for line in forums.strip().split("\n"):
            line = line.strip()
            if line:
                parts = line.split("|")
                if len(parts) >= 2:
                    forum_list.append({"name": parts[0].strip(), "url": parts[1].strip()})
    
    # Config
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
        max_serp_results=max_serp_results if enable_serp else 0
    )
    
    logs = []
    logs.append(f"📋 Client: {client_name}")
    logs.append(f"🔑 Keywords: {len(keywords)}")
    logs.append("")
    
    all_items = []
    
    try:
        # Reddit
        if enable_reddit and subreddit_list:
            progress(0.2, desc="Scraping Reddit...")
            logs.append(f"🔍 Reddit: {len(subreddit_list)} subreddits")
            reddit_items = scrape_reddit(config, logs)
            all_items.extend(reddit_items)
            logs.append(f"   ✅ {len(reddit_items)} posts collectés")
        
        # SERP/PAA
        if enable_serp and max_serp_results > 0:
            progress(0.5, desc="Scraping SERP/PAA...")
            logs.append(f"🔍 SERP/PAA...")
            serp_items = scrape_serp(config, logs)
            all_items.extend(serp_items)
            logs.append(f"   ✅ {len(serp_items)} questions PAA")
        
        # Trustpilot
        if enable_trustpilot and trustpilot_url:
            progress(0.75, desc="Scraping Trustpilot...")
            logs.append(f"🔍 Trustpilot: {max_trustpilot_pages} pages")
            tp_items = scrape_trustpilot(config, logs)
            all_items.extend(tp_items)
            logs.append(f"   ✅ {len(tp_items)} avis collectés")
        
        if not all_items:
            return None, "\n".join(logs) + "\n\n❌ Aucun item collecté."
        
        progress(0.9, desc="Filtrage et export...")
        
        # Filter
        logs.append("")
        accepted, rejected = filter_items(all_items, config)
        logs.append(f"📊 Filtrage: {len(accepted)} acceptés, {rejected} rejetés")
        
        # Export
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{config.client_slug}_{timestamp}.csv"
        output_path = export_to_csv(accepted, filename)
        
        progress(1.0, desc="Terminé!")
        
        logs.append("")
        logs.append(f"✅ **Export terminé: {len(accepted)} items**")
        
        return output_path, "\n".join(logs)
        
    except Exception as e:
        import traceback
        return None, f"❌ Erreur: {str(e)}\n\n{traceback.format_exc()}"


# ============================================
# INTERFACE GRADIO
# ============================================

with gr.Blocks(title="Prompt Finder - Collecte GEO", theme=gr.themes.Soft()) as app:
    
    gr.Markdown("""
    # 🔍 Prompt Finder - Collecte de Questions GEO
    
    Collectez des questions et avis depuis Reddit, Trustpilot et Google PAA.
    """)
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("## ⚙️ Configuration")
            
            client_name = gr.Textbox(
                label="Nom du client",
                placeholder="Ex: Decathlon"
            )
            
            gr.Markdown("### 📄 Fichier Keywords")
            keywords_file = gr.File(
                label="Upload Excel/CSV (colonne 'keywords')",
                file_types=[".xlsx", ".xls", ".csv"]
            )
            keywords_preview = gr.Markdown("*Uploadez un fichier pour voir l'aperçu*")
            
            max_keywords = gr.Slider(
                minimum=1, maximum=500, value=50, step=5,
                label="Limite de keywords"
            )
        
        with gr.Column(scale=2):
            gr.Markdown("## 📡 Sources")
            
            with gr.Tabs():
                with gr.TabItem("🤖 Reddit"):
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
                
                with gr.TabItem("💬 Forums"):
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
                
                with gr.TabItem("⭐ Trustpilot"):
                    enable_trustpilot = gr.Checkbox(label="Activer Trustpilot", value=True)
                    trustpilot_url = gr.Textbox(
                        label="URL Trustpilot",
                        placeholder="https://fr.trustpilot.com/review/www.example.com"
                    )
                    max_trustpilot_pages = gr.Slider(
                        minimum=1, maximum=20, value=5, step=1,
                        label="Nombre de pages"
                    )
                
                with gr.TabItem("🔎 SERP/PAA"):
                    enable_serp = gr.Checkbox(label="Activer SERP/PAA", value=True)
                    max_serp_results = gr.Slider(
                        minimum=0, maximum=100, value=30, step=5,
                        label="Max requêtes SERP"
                    )
                    gr.Markdown("⚠️ Requiert `DATAFORSEO_LOGIN` et `DATAFORSEO_PASSWORD`")
    
    gr.Markdown("---")
    
    with gr.Row():
        run_btn = gr.Button("▶️ Lancer la collecte", variant="primary", size="lg")
    
    with gr.Row():
        with gr.Column():
            output_logs = gr.Textbox(label="📋 Logs", lines=20, interactive=False)
        with gr.Column():
            output_file = gr.File(label="📁 Fichier CSV")
    
    keywords_file.change(fn=preview_keywords, inputs=[keywords_file], outputs=[keywords_preview])
    
    run_btn.click(
        fn=run_scraping,
        inputs=[
            client_name, keywords_file, max_keywords,
            subreddits, forums, trustpilot_url,
            max_posts_per_subreddit, max_results_per_forum,
            max_trustpilot_pages, max_serp_results,
            enable_reddit, enable_forums, enable_trustpilot, enable_serp
        ],
        outputs=[output_file, output_logs]
    )


if __name__ == "__main__":
    app.queue().launch()
