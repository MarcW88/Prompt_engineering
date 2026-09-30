"""
Prompt Finder - Interface Hugging Face Spaces
Collecte de questions et avis pour analyse GEO
"""

import gradio as gr
import pandas as pd
import tempfile
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from utils.config_loader import load_config, Config
from utils.logger import setup_logger, get_logger
from scrapers import ForumScraper, SerpScraper, ReviewScraper
from filters import QualityFilter
from export import Exporter
from storage import RawStorage

# Setup logger
setup_logger("INFO", "./logs")
logger = get_logger("app")


def parse_keywords_file(file_obj) -> list:
    """Parse un fichier Excel/CSV avec colonne 'keywords'"""
    if file_obj is None:
        return []
    
    try:
        if file_obj.name.endswith('.xlsx') or file_obj.name.endswith('.xls'):
            df = pd.read_excel(file_obj.name)
        else:
            df = pd.read_csv(file_obj.name)
        
        # Chercher la colonne keywords (case insensitive)
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
        logger.error(f"Error parsing keywords file: {e}")
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


def create_config_dict(
    client_name: str,
    keywords: list,
    max_keywords: int,
    subreddits: str,
    forums: str,
    trustpilot_url: str,
    max_posts_per_subreddit: int,
    max_results_per_forum: int,
    max_trustpilot_pages: int,
    max_serp_results: int
) -> dict:
    """Crée le dictionnaire de configuration"""
    
    # Limiter les keywords
    limited_keywords = keywords[:max_keywords] if max_keywords > 0 else keywords
    
    # Parser subreddits et forums
    subreddit_list = [s.strip() for s in subreddits.split(",") if s.strip()]
    forum_list = []
    for line in forums.strip().split("\n"):
        line = line.strip()
        if line:
            parts = line.split("|")
            if len(parts) >= 2:
                forum_list.append({"name": parts[0].strip(), "url": parts[1].strip()})
            elif line.startswith("http"):
                forum_list.append({"name": "forum", "url": line})
    
    config_dict = {
        "client": {
            "name": client_name,
            "slug": client_name.lower().replace(" ", "_"),
            "industry": "general"
        },
        "brand_variants": limited_keywords,
        "themes": [],
        "competitors": [],
        "markets": ["FR"],
        "languages": ["fr"],
        "sources": {
            "forums": {
                "enabled": bool(subreddit_list or forum_list),
                "platforms": []
            },
            "reviews": {
                "enabled": bool(trustpilot_url.strip()),
                "platforms": [
                    {
                        "name": "trustpilot",
                        "url": trustpilot_url.strip()
                    }
                ] if trustpilot_url.strip() else []
            },
            "serp": {
                "enabled": max_serp_results > 0,
                "query_templates": ["{brand_variant}"]
            }
        },
        "scraping": {
            "forum": {
                "max_threads": max_posts_per_subreddit,
                "max_replies_per_thread": 0
            },
            "reviews": {
                "max_pages": max_trustpilot_pages,
                "min_rating": 1,
                "max_rating": 5
            },
            "serp": {
                "max_paa_depth": 4,
                "max_suggestions": max_serp_results
            },
            "delay_between_requests": 2,
            "max_retries": 3,
            "timeout": 30
        },
        "filters": {
            "min_text_length": 30,
            "max_text_length": 10000,
            "spam_patterns": ["cliquez ici", "code promo", "lien affilié"],
            "accepted_languages": ["fr", "en"]
        },
        "output": {
            "format": "csv",
            "fields": [
                "id", "source_type", "platform", "theme", "brand_detected",
                "raw_text", "url", "title", "rating", "date", "is_question", "sentiment_hint"
            ]
        }
    }
    
    # Ajouter Reddit si subreddits
    if subreddit_list:
        config_dict["sources"]["forums"]["platforms"].append({
            "name": "reddit",
            "subreddits": subreddit_list
        })
    
    # Ajouter forums génériques
    for forum in forum_list:
        config_dict["sources"]["forums"]["platforms"].append(forum)
    
    return config_dict


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
    """Exécute le scraping avec les paramètres donnés"""
    
    if not client_name:
        return None, "❌ Veuillez entrer un nom de client."
    
    # Parse keywords
    keywords = parse_keywords_file(keywords_file)
    if not keywords:
        return None, "❌ Veuillez uploader un fichier Excel/CSV avec une colonne 'keywords'."
    
    try:
        progress(0.05, desc="Création de la configuration...")
        
        # Create config
        config_dict = create_config_dict(
            client_name, keywords, max_keywords,
            subreddits if enable_reddit else "",
            forums if enable_forums else "",
            trustpilot_url if enable_trustpilot else "",
            max_posts_per_subreddit,
            max_results_per_forum,
            max_trustpilot_pages,
            max_serp_results if enable_serp else 0
        )
        
        # Save temp config
        temp_config_path = tempfile.mktemp(suffix=".yaml")
        with open(temp_config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_dict, f, allow_unicode=True)
        
        config = load_config(temp_config_path)
        
        # Temp storage
        temp_db = tempfile.mktemp(suffix=".db")
        storage = RawStorage(temp_db)
        
        all_items = []
        logs = []
        
        logs.append(f"📋 Client: {client_name}")
        logs.append(f"🔑 Keywords: {len(keywords[:max_keywords])} (limité à {max_keywords})")
        logs.append("")
        
        # Reddit scraping
        if enable_reddit and subreddits.strip():
            progress(0.15, desc="Scraping Reddit...")
            subs = [s.strip() for s in subreddits.split(",") if s.strip()]
            logs.append(f"🔍 Reddit: {len(subs)} subreddits")
            try:
                forum_scraper = ForumScraper(config)
                forum_items = forum_scraper.run()
                reddit_items = [i for i in forum_items if i.platform == "reddit"]
                all_items.extend(reddit_items)
                logs.append(f"   ✅ {len(reddit_items)} posts collectés")
            except Exception as e:
                logs.append(f"   ⚠️ Erreur: {str(e)[:100]}")
        
        # Forums génériques
        if enable_forums and forums.strip():
            progress(0.35, desc="Scraping Forums...")
            logs.append(f"🔍 Forums génériques...")
            try:
                if not enable_reddit:
                    forum_scraper = ForumScraper(config)
                forum_items = forum_scraper.run()
                generic_items = [i for i in forum_items if i.platform != "reddit"]
                all_items.extend(generic_items)
                logs.append(f"   ✅ {len(generic_items)} résultats collectés")
            except Exception as e:
                logs.append(f"   ⚠️ Erreur: {str(e)[:100]}")
        
        # SERP/PAA
        if enable_serp and max_serp_results > 0:
            progress(0.55, desc="Scraping SERP/PAA...")
            logs.append(f"🔍 SERP/PAA...")
            
            if not os.getenv("DATAFORSEO_LOGIN"):
                logs.append("   ⚠️ DATAFORSEO_LOGIN non configuré")
            else:
                try:
                    serp_scraper = SerpScraper(config)
                    serp_items = serp_scraper.run()
                    all_items.extend(serp_items)
                    logs.append(f"   ✅ {len(serp_items)} questions PAA collectées")
                except Exception as e:
                    logs.append(f"   ⚠️ Erreur: {str(e)[:100]}")
        
        # Trustpilot
        if enable_trustpilot and trustpilot_url.strip():
            progress(0.75, desc="Scraping Trustpilot...")
            logs.append(f"🔍 Trustpilot: {max_trustpilot_pages} pages")
            try:
                review_scraper = ReviewScraper(config)
                review_items = review_scraper.run()
                all_items.extend(review_items)
                logs.append(f"   ✅ {len(review_items)} avis collectés")
            except Exception as e:
                logs.append(f"   ⚠️ Erreur: {str(e)[:100]}")
        
        if not all_items:
            return None, "\n".join(logs) + "\n\n❌ Aucun item collecté."
        
        progress(0.85, desc="Filtrage et export...")
        
        # Filter
        logs.append("")
        quality_filter = QualityFilter(config)
        result = quality_filter.filter(all_items)
        logs.append(f"📊 Filtrage: {len(result.accepted)} acceptés, {len(result.rejected)} rejetés")
        
        # Export
        temp_output = Path(tempfile.mkdtemp())
        exporter = Exporter(config, str(temp_output))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{config.client.slug}_{timestamp}.csv"
        
        output_path = exporter.to_csv(result.accepted, filename)
        
        progress(1.0, desc="Terminé!")
        
        logs.append("")
        logs.append(f"✅ **Export terminé: {len(result.accepted)} items**")
        logs.append(f"📁 Fichier: {filename}")
        
        # Cleanup
        os.unlink(temp_config_path)
        os.unlink(temp_db)
        
        return output_path, "\n".join(logs)
        
    except Exception as e:
        logger.error(f"Scraping error: {e}")
        import traceback
        return None, f"❌ Erreur: {str(e)}\n\n{traceback.format_exc()}"


# ============================================
# INTERFACE GRADIO
# ============================================

with gr.Blocks(title="Prompt Finder - Collecte GEO", theme=gr.themes.Soft()) as app:
    
    gr.Markdown("""
    # 🔍 Prompt Finder - Collecte de Questions GEO
    
    Collectez des questions et avis depuis Reddit, Forums, Trustpilot et Google PAA.
    """)
    
    with gr.Row():
        # Colonne gauche: Configuration
        with gr.Column(scale=1):
            gr.Markdown("## ⚙️ Configuration")
            
            client_name = gr.Textbox(
                label="Nom du client",
                placeholder="Ex: Decathlon",
                value=""
            )
            
            gr.Markdown("### 📄 Fichier Keywords")
            keywords_file = gr.File(
                label="Upload Excel/CSV (colonne 'keywords')",
                file_types=[".xlsx", ".xls", ".csv"]
            )
            keywords_preview = gr.Markdown("*Uploadez un fichier pour voir l'aperçu*")
            
            max_keywords = gr.Slider(
                minimum=1, maximum=500, value=50, step=5,
                label="Limite de keywords à traiter"
            )
        
        # Colonne droite: Sources
        with gr.Column(scale=2):
            gr.Markdown("## 📡 Sources")
            
            with gr.Tabs():
                # Tab Reddit
                with gr.TabItem("🤖 Reddit"):
                    enable_reddit = gr.Checkbox(label="Activer Reddit", value=True)
                    subreddits = gr.Textbox(
                        label="Subreddits (séparés par virgule)",
                        placeholder="Ex: running, cycling, france, AskFrance",
                        value="",
                        lines=2
                    )
                    max_posts_per_subreddit = gr.Slider(
                        minimum=10, maximum=200, value=50, step=10,
                        label="Max posts par subreddit"
                    )
                
                # Tab Forums
                with gr.TabItem("💬 Forums"):
                    enable_forums = gr.Checkbox(label="Activer Forums", value=False)
                    forums = gr.Textbox(
                        label="Forums (format: nom|url, un par ligne)",
                        placeholder="randonner-leger|https://www.randonner-leger.org/forum\nskipass|https://www.skipass.com/forums",
                        value="",
                        lines=4
                    )
                    max_results_per_forum = gr.Slider(
                        minimum=10, maximum=100, value=30, step=5,
                        label="Max résultats par forum"
                    )
                
                # Tab Trustpilot
                with gr.TabItem("⭐ Trustpilot"):
                    enable_trustpilot = gr.Checkbox(label="Activer Trustpilot", value=True)
                    trustpilot_url = gr.Textbox(
                        label="URL Trustpilot",
                        placeholder="Ex: https://fr.trustpilot.com/review/www.decathlon.fr",
                        value=""
                    )
                    max_trustpilot_pages = gr.Slider(
                        minimum=1, maximum=20, value=5, step=1,
                        label="Nombre de pages d'avis"
                    )
                
                # Tab SERP
                with gr.TabItem("🔎 SERP/PAA"):
                    enable_serp = gr.Checkbox(label="Activer SERP/PAA (DataForSEO)", value=True)
                    max_serp_results = gr.Slider(
                        minimum=0, maximum=100, value=30, step=5,
                        label="Max résultats SERP par keyword"
                    )
                    gr.Markdown("""
                    ⚠️ **Requiert DataForSEO**
                    
                    Configurez `DATAFORSEO_LOGIN` et `DATAFORSEO_PASSWORD` dans les variables d'environnement.
                    """)
    
    gr.Markdown("---")
    
    # Bouton et résultats
    with gr.Row():
        run_btn = gr.Button("▶️ Lancer la collecte", variant="primary", size="lg")
    
    with gr.Row():
        with gr.Column():
            output_logs = gr.Textbox(
                label="📋 Logs",
                lines=20,
                interactive=False
            )
        with gr.Column():
            output_file = gr.File(label="📁 Fichier CSV exporté")
    
    # Event handlers
    keywords_file.change(
        fn=preview_keywords,
        inputs=[keywords_file],
        outputs=[keywords_preview]
    )
    
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
