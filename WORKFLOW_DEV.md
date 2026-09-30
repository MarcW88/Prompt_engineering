# Workflow Scraping GEO - Brief Dev

## 🎯 Objectif

Construire un système de scraping **modulaire et réutilisable** pour collecter :
- Questions utilisateurs
- Doutes / frustrations
- Comparaisons produits/marques

**Client actuel** : Decathlon  
**Demain** : N'importe quel client (changement de config uniquement)

---

## 🧱 Architecture Globale

```
[Client Config]          ← YAML/JSON par client
       ↓
[Source Discovery]       ← Détection automatique des sources pertinentes
       ↓
[Source-Specific Scraper] ← 1 module par TYPE de source
       ↓
[Raw Data Storage]       ← Stockage brut (CSV/DB)
       ↓
[Quality Filters]        ← Filtres règles simples (pas ML)
       ↓
[Ready-for-ML Corpus]    ← Export final pour analyse
```

---

## 1️⃣ MODULE : Client Config

### Principe
**Aucun nom de marque en dur dans le code.**  
Tout passe par un fichier de configuration.

### Structure attendue (YAML recommandé)

```yaml
client:
  name: "Decathlon"
  slug: "decathlon"

brand_variants:
  - decathlon
  - quechua
  - kipsta
  - domyos
  - btwin
  - kalenji

markets:
  - FR
  - BE

languages:
  - fr

themes:
  - running
  - randonnée
  - vélo
  - fitness
  - camping
  - natation

competitors:
  - intersport
  - go sport
  - sport 2000

scraping:
  max_results_per_source: 100
  max_thread_depth: 2
  min_text_length: 50
  date_range_days: 365
```

### Règle absolue
> Le dev doit pouvoir changer de client **en modifiant uniquement ce fichier**.

---

## 2️⃣ MODULE : Source Discovery

### Types de sources (à implémenter comme interfaces)

| Type | Exemples | Réutilisabilité |
|------|----------|-----------------|
| **Forums** | Reddit, forums spécialisés | ✅ Universel |
| **Avis clients** | Trustpilot, Google Reviews | ✅ Universel |
| **Q&A** | Quora, forums questions | ✅ Universel |
| **SERP Questions** | PAA Google, AlsoAsked | ✅ Universel |

### Sources concrètes pour Decathlon

#### Forums / Communautés
- **Reddit** : r/running, r/cycling, r/CampingGear, r/Fitness (FR/EN)
- **Forums outdoor FR** : randonner-leger.org, skipass.com
- **Forums running** : jogging-plus.com (forum)
- **Forums vélo** : velotaf.com, forum.hardware.fr/sports

#### Avis clients
- **Trustpilot** : trustpilot.com/review/decathlon.fr
- **Google Reviews** : Magasins Decathlon (via Places API ou scraping)

#### Q&A
- **Quora** : recherche par thème sport
- **Reddit AskFrance** : questions équipement

### Logique de découverte
```
Pour chaque THEME dans config:
    Pour chaque TYPE_SOURCE:
        Construire requête = THEME + BRAND_VARIANTS
        Identifier URLs pertinentes
        Stocker dans source_registry
```

---

## 3️⃣ MODULE : Source-Specific Scrapers

### Principe
**1 scraper = 1 type de contenu**, pas 1 site.

### A. Forum Scraper

**Input** : URL forum + mots-clés  
**Output** : Liste de threads avec questions

**Étapes** :
1. Recherche interne forum OU Google site:forum.com
2. Identifier pages "thread" (pattern URL)
3. Extraire :
   - Titre du thread
   - Premier message (question)
   - 1-2 meilleures réponses
4. Stop (pas de pagination profonde)

**Configurable** :
- `max_threads` : nombre max de threads
- `max_replies` : réponses par thread
- `question_patterns` : regex pour détecter questions

### B. Review Scraper

**Input** : URL page avis marque  
**Output** : Liste d'avis filtrés

**Étapes** :
1. Identifier structure page avis
2. Filtrer par note (≤ 3 étoiles prioritaires)
3. Extraire texte brut + metadata
4. Paginer jusqu'au seuil

**Configurable** :
- `max_rating` : note max à inclure
- `min_length` : longueur min texte
- `max_pages` : pagination max

### C. SERP Question Scraper

**Input** : Requêtes thématiques  
**Output** : Questions PAA / suggestions

**Étapes** :
1. Construire requêtes : `{theme} {brand}` + variantes
2. Extraire PAA (People Also Ask)
3. Extraire suggestions autocomplete
4. Dédupliquer

**Configurable** :
- `query_templates` : patterns de requêtes
- `max_paa_depth` : profondeur PAA

---

## 4️⃣ MODULE : Raw Data Storage

### Principe
**Tout stocker en brut, AVANT tout traitement.**

### Schema de données

| Champ | Type | Description |
|-------|------|-------------|
| `id` | string | UUID unique |
| `source_type` | enum | forum / review / serp / qa |
| `platform` | string | reddit / trustpilot / etc |
| `brand` | string | marque détectée |
| `theme` | string | thème associé |
| `raw_text` | text | contenu brut |
| `url` | string | source |
| `title` | string | titre si applicable |
| `rating` | int | note si avis |
| `date` | datetime | date publication |
| `language` | string | langue détectée |
| `scraped_at` | datetime | date scraping |

### Format recommandé
- **Dev** : SQLite (simple, portable)
- **Prod** : PostgreSQL ou export CSV

### Règle
> Une ligne = une unité textuelle brute (1 post, 1 avis, 1 question)

---

## 5️⃣ MODULE : Quality Filters

### Principe
Filtres **règles simples**, pas de ML ici.

### Filtres à implémenter

| Filtre | Règle | Configurable |
|--------|-------|--------------|
| Longueur min | `len(text) >= min_length` | ✅ |
| Langue | `detected_lang in config.languages` | ✅ |
| Spam patterns | regex spam/promo | ✅ |
| Doublons | hash texte | ❌ |
| Hors-sujet | aucun mot-clé thème/marque | ✅ |

### Output
- Corpus filtré → `corpus_clean.csv`
- Rejetés avec raison → `corpus_rejected.csv`

---

## 6️⃣ MODULE : Export Ready-for-ML

### Format final

```csv
id,source_type,platform,theme,text,url,date,is_question,sentiment_hint
```

### Enrichissements simples (règles)
- `is_question` : détection "?" ou patterns interrogatifs
- `sentiment_hint` : négatif si note ≤ 2 ou mots-clés frustration

---

## 📁 Structure de fichiers recommandée

```
prompt_finder/
├── config/
│   ├── decathlon.yaml      ← Config client
│   └── _template.yaml      ← Template vide
├── scrapers/
│   ├── base_scraper.py     ← Interface commune
│   ├── forum_scraper.py
│   ├── review_scraper.py
│   └── serp_scraper.py
├── storage/
│   ├── raw_storage.py      ← Gestion stockage brut
│   └── schema.sql
├── filters/
│   ├── quality_filter.py
│   └── dedup.py
├── utils/
│   ├── config_loader.py
│   └── logger.py
├── output/
│   ├── raw/                ← Données brutes
│   ├── clean/              ← Données filtrées
│   └── rejected/           ← Données rejetées
├── main.py                 ← Orchestrateur
└── requirements.txt
```

---

## 🔧 Variables d'environnement

```env
# API Keys (si nécessaire)
SERP_API_KEY=xxx           # Pour SerpAPI ou similaire
REDDIT_CLIENT_ID=xxx       # Reddit API
REDDIT_CLIENT_SECRET=xxx

# Config
CONFIG_PATH=./config/decathlon.yaml
OUTPUT_DIR=./output
LOG_LEVEL=INFO
```

---

## ⚠️ Points d'attention techniques

### Rate limiting
- Implémenter délais entre requêtes
- Respecter robots.txt
- Rotation user-agents

### Gestion erreurs
- Retry avec backoff exponentiel
- Log toutes les erreurs
- Ne jamais crash sur une source

### Monitoring
- Compteurs par source
- Alertes si 0 résultats
- Temps d'exécution par module

---

## ✅ Checklist Dev

- [ ] Architecture modulaire (1 module = 1 responsabilité)
- [ ] Config client séparée (YAML)
- [ ] Aucun hardcoding marque/thème
- [ ] Scraping par TYPE de source, pas par site
- [ ] Stockage brut systématique
- [ ] Logs structurés
- [ ] Gestion erreurs robuste
- [ ] Rate limiting
- [ ] Export CSV standardisé
- [ ] Rejouable sur autre client = changement config uniquement

---

## 🚀 Pour lancer sur un nouveau client

1. Copier `config/_template.yaml` → `config/nouveau_client.yaml`
2. Remplir : marque, variantes, thèmes, marchés
3. Lancer : `python main.py --config config/nouveau_client.yaml`
4. Récupérer : `output/clean/corpus.csv`

**Temps estimé changement client : 15 minutes**
