# Prompt Finder - Hugging Face Spaces

Interface Gradio pour la collecte de questions et avis pour analyse GEO.

## Déploiement sur Hugging Face Spaces

### 1. Créer un nouveau Space

1. Aller sur https://huggingface.co/spaces
2. Cliquer "Create new Space"
3. Choisir:
   - **SDK**: Gradio
   - **Hardware**: CPU Basic (gratuit)
   - **Visibility**: Private (recommandé)

### 2. Configurer les secrets

Dans Settings > Repository secrets, ajouter:

```
DATAFORSEO_LOGIN=votre_login
DATAFORSEO_PASSWORD=votre_password
```

### 3. Uploader les fichiers

Structure requise dans le Space:

```
/
├── app.py                 # Interface Gradio (ce fichier)
├── requirements.txt       # Dépendances
├── utils/
│   ├── __init__.py
│   ├── config_loader.py
│   └── logger.py
├── models/
│   ├── __init__.py
│   └── raw_item.py
├── scrapers/
│   ├── __init__.py
│   ├── base_scraper.py
│   ├── forum_scraper.py
│   ├── review_scraper.py
│   └── serp_scraper.py
├── filters/
│   ├── __init__.py
│   └── quality_filter.py
├── storage/
│   ├── __init__.py
│   └── raw_storage.py
└── export/
    ├── __init__.py
    └── exporter.py
```

### 4. Commandes pour copier les fichiers

```bash
# Depuis le dossier Prompt_Finder
cp huggingface/app.py .
cp huggingface/requirements.txt .

# Ou cloner le repo et push vers HF
git clone https://huggingface.co/spaces/VOTRE_USERNAME/prompt-finder
cp -r utils models scrapers filters storage export prompt-finder/
cp huggingface/app.py prompt-finder/
cp huggingface/requirements.txt prompt-finder/
cd prompt-finder
git add .
git commit -m "Initial commit"
git push
```

## Utilisation locale

```bash
cd /Users/marc/Desktop/Prompt_Finder
pip install gradio
python huggingface/app.py
```

L'interface sera accessible sur http://localhost:7860

## Fonctionnalités

- **Reddit**: Collecte de posts via API JSON publique
- **Trustpilot**: Scraping d'avis clients
- **SERP/PAA**: Questions "People Also Ask" via DataForSEO
- **Export CSV**: Téléchargement direct du fichier

## Limitations Hugging Face Spaces

- **CPU Basic**: Temps de scraping plus long
- **Timeout**: 60s max par requête (réduire les limites si nécessaire)
- **Storage**: Fichiers temporaires uniquement
