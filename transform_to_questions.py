"""
Transform Forum/Reddit Content to GEO Questions
Utilise OpenAI pour transformer les discussions en questions exploitables
"""

import pandas as pd
import os
import json
import time
from datetime import datetime
from openai import OpenAI

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
INPUT_FILE = None  # Sera défini par l'utilisateur
OUTPUT_FILE = None  # Sera généré automatiquement

# Critères pour bonnes questions GEO
SYSTEM_PROMPT = """Tu es un expert en analyse de contenu et génération de questions pour l'optimisation GEO (Generative Engine Optimization).

Ta mission : transformer des discussions de forums/Reddit en questions que les utilisateurs poseraient naturellement à un assistant IA comme ChatGPT.

CRITÈRES pour les questions générées :
1. Proche du langage utilisateur (conversationnel, pas trop SEO)
2. Assez large pour englober plusieurs intentions similaires
3. Assez spécifique pour refléter une intention claire
4. Neutre/sans marque (pour tester si une marque émerge naturellement)
5. En français

EXEMPLES de bonnes questions :
- "Quels sont les bienfaits du collagène marin pour la peau ?"
- "Est-ce que la glutamine aide vraiment pour la récupération musculaire ?"
- "Quels compléments alimentaires prendre pour améliorer le sommeil ?"

FORMAT DE SORTIE : Retourne UNIQUEMENT un JSON avec cette structure :
{
    "questions": [
        "Question 1",
        "Question 2",
        "Question 3"
    ],
    "theme_detected": "thème principal détecté"
}

Génère 1 à 3 questions pertinentes par contenu. Si le contenu n'est pas exploitable, retourne un tableau vide."""


def load_csv(filepath: str) -> pd.DataFrame:
    """Charge le CSV d'entrée"""
    print(f"📂 Chargement de {filepath}...")
    df = pd.read_csv(filepath)
    print(f"   ✅ {len(df)} lignes chargées")
    return df


def filter_forums_to_transform(df: pd.DataFrame) -> pd.DataFrame:
    """Filtre TOUS les contenus forums/reddit à transformer"""
    # Garder tous les items de type forum (reddit, doctissimo, davidmanise, etc.)
    filtered = df[df['source_type'] == 'forum'].copy()
    print(f"📊 {len(filtered)} items forums/reddit à transformer")
    
    # Afficher les sources détectées
    if len(filtered) > 0:
        forum_sources = filtered['platform'].value_counts()
        for source, count in forum_sources.items():
            print(f"   - {source}: {count} items")
    
    return filtered


def get_paa_questions(df: pd.DataFrame) -> pd.DataFrame:
    """Récupère les questions observées PAA et GSC à conserver telles quelles"""
    existing = df[df['source_type'].isin(['serp', 'gsc_conversation'])].copy()
    print(f"📊 {len(existing)} questions PAA/GSC conservées")
    return existing


def transform_to_questions(client: OpenAI, text: str, title: str, platform: str) -> dict:
    """Transforme un contenu en questions via OpenAI"""
    
    user_prompt = f"""Contenu à analyser (source: {platform}):

Titre: {title}

Texte: {text}

Génère des questions GEO pertinentes basées sur ce contenu."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parser le JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        result = json.loads(content)
        return result
        
    except json.JSONDecodeError as e:
        print(f"   ⚠️ Erreur JSON: {str(e)[:50]}")
        return {"questions": [], "theme_detected": ""}
    except Exception as e:
        print(f"   ⚠️ Erreur API: {str(e)[:50]}")
        return {"questions": [], "theme_detected": ""}


def process_batch(df: pd.DataFrame, client: OpenAI, batch_size: int = 10) -> list:
    """Traite les items par batch"""
    all_questions = []
    total = len(df)
    
    for idx, row in df.iterrows():
        current = len(all_questions) + 1
        print(f"   [{current}/{total}] {row['platform']}: {row['title'][:40]}...")
        
        result = transform_to_questions(
            client,
            row['raw_text'],
            row['title'],
            row['platform']
        )
        
        original_platform = str(row['platform']) if pd.notna(row['platform']) else 'unknown'
        for q_idx, question in enumerate(result.get('questions', [])):
            all_questions.append({
                'id': f"gen_{idx}_{q_idx}",
                'source_type': 'generated',
                'platform': original_platform,  # Garde le nom du forum original
                'theme': result.get('theme_detected', ''),
                'brand_detected': '',
                'raw_text': question,
                'url': row['url'] if pd.notna(row['url']) else '',
                'title': question,
                'rating': None,
                'date': None,
                'is_question': True,
                'sentiment_hint': 'neutral',
                'original_title': row['title'] if pd.notna(row['title']) else ''
            })
        
        # Rate limiting
        time.sleep(0.5)
    
    return all_questions


def main(input_file: str, output_file: str = None):
    """Fonction principale"""
    
    print("\n" + "="*60)
    print("🔄 TRANSFORMATION FORUMS → QUESTIONS GEO")
    print("="*60 + "\n")
    
    # Vérifier la clé API
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY non définie!")
        print("   Exécute: export OPENAI_API_KEY='ta-clé-api'")
        return
    
    # Initialiser le client OpenAI
    client = OpenAI(api_key=api_key)
    
    # Charger les données
    df = load_csv(input_file)
    
    # Séparer PAA (à conserver) et forums (à transformer)
    paa_questions = get_paa_questions(df)
    to_transform = filter_forums_to_transform(df)
    
    if len(to_transform) == 0:
        print("⚠️ Aucun contenu à transformer!")
        return
    
    # Transformer les contenus
    print(f"\n🤖 Transformation via OpenAI (gpt-4o-mini)...")
    generated_questions = process_batch(to_transform, client)
    
    print(f"\n✅ {len(generated_questions)} questions générées")
    
    # Créer le DataFrame final
    generated_df = pd.DataFrame(generated_questions)
    
    # Combiner avec les PAA
    paa_for_merge = paa_questions[['id', 'source_type', 'platform', 'theme', 
                                    'brand_detected', 'raw_text', 'url', 'title',
                                    'rating', 'date', 'is_question', 'sentiment_hint']].copy()
    paa_for_merge['original_title'] = ''  # PAA n'ont pas de titre original
    
    # Colonnes communes
    common_cols = ['id', 'source_type', 'platform', 'theme', 'brand_detected', 
                   'raw_text', 'url', 'title', 'rating', 'date', 'is_question', 
                   'sentiment_hint', 'original_title']
    
    final_df = pd.concat([
        paa_for_merge[common_cols],
        generated_df[common_cols]
    ], ignore_index=True)
    
    # Générer le nom du fichier de sortie
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f"{base_name}_questions_{timestamp}.csv"
    
    # Sauvegarder
    final_df.to_csv(output_file, index=False)
    
    print(f"\n" + "="*60)
    print(f"📊 RÉSUMÉ")
    print(f"="*60)
    print(f"   Questions PAA (conservées): {len(paa_questions)}")
    print(f"   Questions générées (forums): {len(generated_questions)}")
    print(f"   TOTAL: {len(final_df)}")
    print(f"\n📁 Export: {output_file}")
    print("="*60 + "\n")
    
    return final_df


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python transform_to_questions.py <input_csv> [output_csv]")
        print("\nExemple:")
        print("  python transform_to_questions.py lepivits_20260202.csv")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    main(input_file, output_file)
