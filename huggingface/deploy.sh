#!/bin/bash
# Script de déploiement vers Hugging Face Spaces

# Configuration
HF_USERNAME="VOTRE_USERNAME"  # Remplacer par votre username HF
SPACE_NAME="prompt-finder"

# Créer un dossier temporaire pour le déploiement
DEPLOY_DIR="/tmp/hf_deploy_$$"
mkdir -p "$DEPLOY_DIR"

echo "📦 Préparation des fichiers..."

# Copier les modules nécessaires
cp -r ../utils "$DEPLOY_DIR/"
cp -r ../models "$DEPLOY_DIR/"
cp -r ../scrapers "$DEPLOY_DIR/"
cp -r ../filters "$DEPLOY_DIR/"
cp -r ../storage "$DEPLOY_DIR/"
cp -r ../export "$DEPLOY_DIR/"

# Copier les fichiers HF
cp app.py "$DEPLOY_DIR/"
cp requirements.txt "$DEPLOY_DIR/"
cp README.md "$DEPLOY_DIR/"

echo "📁 Fichiers préparés dans: $DEPLOY_DIR"
echo ""
echo "Structure:"
find "$DEPLOY_DIR" -type f -name "*.py" | head -20

echo ""
echo "📤 Pour déployer sur Hugging Face:"
echo ""
echo "1. Installer huggingface_hub:"
echo "   pip install huggingface_hub"
echo ""
echo "2. Se connecter:"
echo "   huggingface-cli login"
echo ""
echo "3. Créer le Space (si pas encore fait):"
echo "   huggingface-cli repo create $SPACE_NAME --type space --space_sdk gradio"
echo ""
echo "4. Cloner et pusher:"
echo "   cd $DEPLOY_DIR"
echo "   git init"
echo "   git remote add origin https://huggingface.co/spaces/$HF_USERNAME/$SPACE_NAME"
echo "   git add ."
echo "   git commit -m 'Deploy Prompt Finder'"
echo "   git push -u origin main"
echo ""
echo "5. Configurer les secrets dans Settings > Repository secrets:"
echo "   DATAFORSEO_LOGIN=votre_login"
echo "   DATAFORSEO_PASSWORD=votre_password"
