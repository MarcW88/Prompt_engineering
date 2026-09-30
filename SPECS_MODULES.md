# Spécifications Techniques des Modules

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (Orchestrateur)                  │
├─────────────────────────────────────────────────────────────────┤
│  config_loader  │  logger  │  rate_limiter  │  error_handler   │
├─────────────────────────────────────────────────────────────────┤
│   ForumScraper  │  ReviewScraper  │  SerpScraper  │  QAScraper │
├─────────────────────────────────────────────────────────────────┤
│                      BaseScraper (Interface)                    │
├─────────────────────────────────────────────────────────────────┤
│              RawStorage  │  QualityFilter  │  Exporter          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module 1 : BaseScraper (Interface)

### Responsabilité
Définir le contrat que tous les scrapers doivent respecter.

### Méthodes obligatoires

```
class BaseScraper:
    
    def __init__(config, logger)
        # Initialisation avec config client
    
    def discover_sources(themes, brand_variants) -> List[SourceURL]
        # Trouver les URLs à scraper
    
    def scrape(source_url) -> List[RawItem]
        # Extraire les données brutes
    
    def validate(raw_item) -> bool
        # Validation basique avant stockage
```

### Structure RawItem (output standard)

```
RawItem:
    id: str (UUID)
    source_type: enum [forum, review, serp, qa]
    platform: str
    brand: str | null
    theme: str | null
    raw_text: str
    url: str
    title: str | null
    rating: int | null
    date: datetime | null
    metadata: dict
    scraped_at: datetime
```

---

## Module 2 : ForumScraper

### Sources supportées
- Reddit (via API PRAW)
- Forums génériques (via recherche Google site:)

### Flux de données

```
Input: config.sources.forums
  ↓
Pour chaque plateforme:
  ↓
[Recherche] → mots-clés = themes × brand_variants
  ↓
[Filtrage] → threads avec "?" ou patterns question
  ↓
[Extraction] → titre + premier post + N réponses
  ↓
Output: List[RawItem]
```

### Paramètres configurables

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| max_threads | int | 50 | Threads max par recherche |
| max_replies | int | 3 | Réponses par thread |
| question_patterns | list | ["?", "comment", "pourquoi"...] | Détection questions |
| search_method | enum | api/google_site | Méthode recherche |

### Gestion Reddit spécifique
- Utiliser PRAW (Python Reddit API Wrapper)
- Authentification OAuth2
- Respecter rate limits Reddit (60 req/min)

### Gestion forums génériques
- Recherche Google : `site:forum.com "mot-clé"`
- Parser HTML avec BeautifulSoup
- Détecter structure thread (heuristiques)

---

## Module 3 : ReviewScraper

### Sources supportées
- Trustpilot
- Google Reviews (via Places API)
- Pattern générique pour autres plateformes

### Flux de données

```
Input: config.sources.reviews
  ↓
Pour chaque plateforme:
  ↓
[Accès page] → URL avis marque
  ↓
[Filtrage] → rating <= max_rating
  ↓
[Extraction] → texte + note + date
  ↓
[Pagination] → jusqu'à max_pages
  ↓
Output: List[RawItem]
```

### Paramètres configurables

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| max_rating | int | 3 | Note max à inclure |
| min_text_length | int | 100 | Longueur min avis |
| max_pages | int | 10 | Pages max à scraper |
| include_all | bool | false | Inclure toutes notes |

### Trustpilot spécifique
- Structure HTML stable
- Pagination par URL (?page=N)
- Attention : anti-bot actif → rotation headers

### Google Reviews spécifique
- Préférer Places API (officiel)
- Alternative : scraping Maps (fragile)
- Nécessite place_id par magasin

---

## Module 4 : SerpScraper

### Sources supportées
- Google PAA (People Also Ask)
- Google Autocomplete
- AlsoAsked.com (optionnel)

### Flux de données

```
Input: config.sources.serp.query_templates
  ↓
[Génération requêtes] → templates × themes × brands
  ↓
[Requête SERP] → via API ou scraping
  ↓
[Extraction PAA] → questions liées
  ↓
[Extraction suggestions] → autocomplete
  ↓
[Déduplication]
  ↓
Output: List[RawItem]
```

### Paramètres configurables

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| query_templates | list | [...] | Templates requêtes |
| max_paa_depth | int | 3 | Profondeur PAA |
| max_suggestions | int | 10 | Suggestions max |
| market | str | FR | Marché Google |

### Options d'implémentation

| Méthode | Avantages | Inconvénients |
|---------|-----------|---------------|
| SerpAPI | Fiable, structuré | Payant |
| Scraping direct | Gratuit | Fragile, captcha |
| DataForSEO | Pro, complet | Payant |

**Recommandation** : SerpAPI pour MVP, scraping en fallback.

---

## Module 5 : RawStorage

### Responsabilité
Stocker TOUTES les données brutes, sans transformation.

### Interface

```
class RawStorage:
    
    def save(items: List[RawItem]) -> int
        # Sauvegarder items, retourne count
    
    def get_all(filters: dict) -> List[RawItem]
        # Récupérer avec filtres optionnels
    
    def exists(url: str) -> bool
        # Vérifier si déjà scrapé
    
    def get_stats() -> dict
        # Statistiques stockage
```

### Schema SQLite

```sql
CREATE TABLE raw_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    brand TEXT,
    theme TEXT,
    raw_text TEXT NOT NULL,
    url TEXT UNIQUE,
    title TEXT,
    rating INTEGER,
    date TEXT,
    metadata TEXT,  -- JSON
    scraped_at TEXT NOT NULL,
    client_slug TEXT NOT NULL
);

CREATE INDEX idx_source ON raw_items(source_type);
CREATE INDEX idx_platform ON raw_items(platform);
CREATE INDEX idx_client ON raw_items(client_slug);
```

### Règles
- **Jamais** modifier les données brutes
- Toujours vérifier `exists()` avant scraping
- Backup automatique avant chaque run

---

## Module 6 : QualityFilter

### Responsabilité
Filtrer le corpus avec des règles simples (pas de ML).

### Interface

```
class QualityFilter:
    
    def __init__(config.filters)
    
    def filter(items: List[RawItem]) -> FilterResult
        # Retourne accepted + rejected avec raisons
    
    def add_rule(rule: FilterRule)
        # Ajouter règle custom
```

### Règles implémentées

| Règle | Logique | Configurable |
|-------|---------|--------------|
| min_length | `len(text) >= N` | ✅ min_text_length |
| max_length | `len(text) <= N` | ✅ max_text_length |
| language | `detect_lang(text) in langs` | ✅ accepted_languages |
| spam | `not any(p in text for p in patterns)` | ✅ spam_patterns |
| duplicate | `hash(text) not in seen` | ❌ |
| has_keyword | `any(kw in text for kw in keywords)` | ✅ |

### Output

```
FilterResult:
    accepted: List[RawItem]
    rejected: List[RejectedItem]

RejectedItem:
    item: RawItem
    reason: str
    rule: str
```

---

## Module 7 : Exporter

### Responsabilité
Exporter le corpus filtré dans le format final.

### Interface

```
class Exporter:
    
    def to_csv(items, path, fields)
    
    def to_json(items, path)
    
    def enrich(items) -> List[EnrichedItem]
        # Ajouter is_question, sentiment_hint
```

### Enrichissements (règles simples)

```
is_question:
    - Contient "?"
    - Commence par "comment", "pourquoi", "quel", "où"...
    - Pattern interrogatif détecté

sentiment_hint:
    - "negative" si rating <= 2
    - "negative" si mots-clés frustration
    - "neutral" sinon
```

### Format CSV final

```csv
id,source_type,platform,theme,brand_detected,text,url,title,rating,date,is_question,sentiment_hint
```

---

## Module 8 : Orchestrateur (main.py)

### Flux principal

```python
def main(config_path):
    # 1. Charger config
    config = load_config(config_path)
    
    # 2. Initialiser modules
    storage = RawStorage(config)
    scrapers = init_scrapers(config)
    filter = QualityFilter(config)
    exporter = Exporter(config)
    
    # 3. Scraper chaque source
    for scraper in scrapers:
        if scraper.enabled:
            items = scraper.run()
            storage.save(items)
    
    # 4. Filtrer
    raw_items = storage.get_all()
    result = filter.filter(raw_items)
    
    # 5. Exporter
    exporter.to_csv(result.accepted, "corpus_clean.csv")
    exporter.to_csv(result.rejected, "corpus_rejected.csv")
    
    # 6. Stats
    print_stats(result)
```

### Arguments CLI

```
python main.py --config config/decathlon.yaml
               --output ./output
               --sources forum,review  # optionnel, filtre sources
               --dry-run               # optionnel, pas de scraping
               --verbose
```

---

## Dépendances Python

```
# requirements.txt

# Scraping
requests>=2.28.0
beautifulsoup4>=4.11.0
lxml>=4.9.0
praw>=7.6.0              # Reddit API

# SERP (choisir un)
google-search-results    # SerpAPI
# ou scraping manuel

# Storage
sqlite3                  # Built-in

# Utils
pyyaml>=6.0
python-dotenv>=0.21.0
langdetect>=1.0.9

# Rate limiting
ratelimit>=2.2.1
backoff>=2.2.1

# Logging
loguru>=0.6.0
```

---

## Gestion des erreurs

### Stratégie globale
- **Never crash** : une source en erreur ne bloque pas les autres
- **Log everything** : toutes les erreurs sont tracées
- **Retry with backoff** : 3 tentatives avec délai exponentiel

### Codes erreur

| Code | Signification | Action |
|------|---------------|--------|
| E001 | Source inaccessible | Skip + log |
| E002 | Rate limit atteint | Wait + retry |
| E003 | Structure HTML changée | Alert + skip |
| E004 | Auth failed | Stop + alert |
| E005 | Config invalide | Stop |

---

## Monitoring

### Métriques à tracker

```
- items_scraped_total (par source, par run)
- items_filtered_out (par règle)
- errors_count (par type)
- run_duration_seconds
- sources_success_rate
```

### Logs structurés

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "module": "forum_scraper",
  "action": "scrape_complete",
  "platform": "reddit",
  "items_count": 45,
  "duration_ms": 12340
}
```
