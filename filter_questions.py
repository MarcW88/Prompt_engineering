"""
Script de filtrage et pertinence des questions GEO
Analyse les questions, évalue leur pertinence pour un client donné,
déduplique les questions similaires et limite au nombre souhaité.
"""

import pandas as pd
import numpy as np
import os
import json
import argparse
from datetime import datetime
from typing import List, Dict, Tuple
from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️ OpenAI non installé. Exécutez: pip install openai")

try:
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️ sklearn non installé. Exécutez: pip install scikit-learn")


# ============================================
# CONFIGURATION
# ============================================

DOMAIN_ANALYSIS_PROMPT = """Tu es un expert en analyse de marques et domaines d'activité.

Analyse le domaine/la marque suivante et fournis une description structurée de :
1. Son secteur d'activité principal
2. Ses produits/services clés
3. Ses cibles clients
4. Les thématiques pertinentes pour cette marque
5. Les mots-clés associés

FORMAT JSON:
{
    "brand": "nom de la marque",
    "sector": "secteur principal",
    "products_services": ["liste", "des", "produits/services"],
    "target_audience": ["cibles", "clients"],
    "relevant_themes": ["thème1", "thème2", ...],
    "keywords": ["mot1", "mot2", ...]
}"""

RELEVANCE_PROMPT = """Tu es un expert en GEO (Generative Engine Optimization).

CONTEXTE MARQUE:
{brand_context}

MISSION: Évalue si chaque question est pertinente pour tester la visibilité de cette marque dans les réponses des moteurs génératifs (ChatGPT, Perplexity, Claude).

Une question est PERTINENTE si:
- Elle concerne un produit/service que la marque propose
- Un utilisateur pourrait naturellement poser cette question et s'attendre à voir la marque mentionnée
- Elle est liée au secteur d'activité de la marque

Une question est NON PERTINENTE si:
- Elle concerne un domaine où la marque n'opère pas
- Elle est trop générique ou hors sujet
- Elle concerne un concurrent direct sans lien avec les produits de la marque

QUESTIONS À ÉVALUER:
{questions}

FORMAT JSON (liste):
[
    {{"question": "la question", "is_relevant": true/false, "reason": "explication courte", "relevance_score": 0-100}},
    ...
]"""

DEDUP_PROMPT = """Tu es un expert en analyse sémantique pour le GEO (Generative Engine Optimization).

OBJECTIF: Identifier les questions qui testent LA MÊME INTENTION utilisateur et n'en garder qu'une par intention.

RÈGLES DE DÉDUPLICATION:
1. Deux questions sont SIMILAIRES si elles cherchent la même information, même avec des formulations différentes
   - "Comment choisir le meilleur ballon de foot ?" = "Quel ballon de foot est le meilleur ?" (MÊME INTENTION: recommandation ballon)
   - "Quelle taille de ballon choisir ?" ≠ "Quel ballon est le meilleur ?" (INTENTIONS DIFFÉRENTES: taille vs qualité)

2. Garde la formulation la plus NATURELLE et CONVERSATIONNELLE (comme on parlerait à ChatGPT)

3. IMPORTANT: Ne supprime PAS trop de questions. En cas de doute, garde les deux.
   - Garde les questions qui apportent une NUANCE différente
   - Garde les questions avec des ANGLES différents (prix, qualité, usage, comparaison)

QUESTIONS À ANALYSER:
{questions}

FORMAT JSON:
{{
    "kept_questions": ["question1", "question2", ...],
    "removed_duplicates": [
        {{"removed": "question supprimée", "similar_to": "question gardée", "reason": "même intention"}}
    ]
}}"""


# ============================================
# FONCTIONS PRINCIPALES
# ============================================

def analyze_domain(client, domain: str) -> Dict:
    """Analyse le domaine/marque pour comprendre son activité"""
    print(f"\n🔍 Analyse du domaine: {domain}")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": DOMAIN_ANALYSIS_PROMPT},
                {"role": "user", "content": f"Analyse cette marque/domaine: {domain}"}
            ],
            temperature=0.3,
            max_tokens=800
        )
        content = response.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        result = json.loads(content)
        print(f"   ✅ Secteur: {result.get('sector', 'N/A')}")
        print(f"   ✅ Produits/Services: {', '.join(result.get('products_services', [])[:5])}")
        return result
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        return {"brand": domain, "sector": "unknown", "products_services": [], "keywords": []}


def evaluate_relevance_batch(client, questions: List[str], brand_context: Dict, batch_size: int = 20) -> List[Dict]:
    """Évalue la pertinence des questions par batch"""
    all_results = []
    brand_context_str = json.dumps(brand_context, ensure_ascii=False, indent=2)
    
    for i in range(0, len(questions), batch_size):
        batch = questions[i:i+batch_size]
        questions_str = "\n".join([f"- {q}" for q in batch])
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": RELEVANCE_PROMPT.format(
                        brand_context=brand_context_str,
                        questions=questions_str
                    )},
                    {"role": "user", "content": "Évalue ces questions."}
                ],
                temperature=0.2,
                max_tokens=2000
            )
            content = response.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            batch_results = json.loads(content)
            all_results.extend(batch_results)
        except Exception as e:
            print(f"   ⚠️ Erreur batch {i//batch_size + 1}: {e}")
            # Fallback: marquer comme pertinent par défaut
            for q in batch:
                all_results.append({
                    "question": q,
                    "is_relevant": True,
                    "reason": "Évaluation échouée - conservé par défaut",
                    "relevance_score": 50
                })
    
    return all_results


def deduplicate_by_category(client, df: pd.DataFrame, category_col: str = "intent_label") -> pd.DataFrame:
    """Déduplique les questions similaires dans chaque catégorie"""
    print(f"\n🔄 Déduplication par catégorie ({category_col})...")
    
    categories = df[category_col].unique()
    kept_indices = []
    removed_count = 0
    
    for cat in categories:
        cat_df = df[df[category_col] == cat]
        
        if len(cat_df) <= 2:
            # Pas besoin de dédupliquer si 2 questions ou moins
            kept_indices.extend(cat_df.index.tolist())
            continue
        
        questions = cat_df['question'].tolist() if 'question' in cat_df.columns else cat_df['prompt'].tolist()
        questions_str = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)])
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": DEDUP_PROMPT.format(questions=questions_str)},
                    {"role": "user", "content": "Identifie et supprime les doublons sémantiques."}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            content = response.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            kept_questions = result.get("kept_questions", questions)
            
            # Trouver les indices des questions gardées
            question_col = 'question' if 'question' in cat_df.columns else 'prompt'
            for idx, row in cat_df.iterrows():
                if row[question_col] in kept_questions:
                    kept_indices.append(idx)
                else:
                    removed_count += 1
                    
        except Exception as e:
            print(f"   ⚠️ Erreur catégorie {cat}: {e}")
            # En cas d'erreur, garder toutes les questions
            kept_indices.extend(cat_df.index.tolist())
    
    print(f"   ✅ {removed_count} doublons supprimés")
    return df.loc[kept_indices].copy()


def get_embeddings(client, texts: List[str], batch_size: int = 100) -> np.ndarray:
    """Obtient les embeddings pour déduplication par similarité"""
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
    
    return np.array(all_embeddings)


def deduplicate_by_similarity(client, df: pd.DataFrame, similarity_threshold: float = 0.92) -> pd.DataFrame:
    """Déduplique par similarité cosinus (plus rapide que GPT pour gros volumes)"""
    print(f"\n🔄 Déduplication par similarité (seuil: {similarity_threshold})...")
    
    question_col = 'question' if 'question' in df.columns else 'prompt'
    questions = df[question_col].tolist()
    
    # Obtenir embeddings
    print("   📊 Calcul des embeddings...")
    embeddings = get_embeddings(client, questions)
    
    # Calculer similarités
    print("   📊 Calcul des similarités...")
    similarities = cosine_similarity(embeddings)
    
    # Identifier les doublons
    kept_indices = []
    removed_indices = set()
    
    for i in range(len(questions)):
        if i in removed_indices:
            continue
        kept_indices.append(i)
        
        # Marquer les questions trop similaires comme doublons
        for j in range(i + 1, len(questions)):
            if j not in removed_indices and similarities[i][j] > similarity_threshold:
                removed_indices.add(j)
    
    print(f"   ✅ {len(removed_indices)} doublons supprimés")
    return df.iloc[kept_indices].copy()


def limit_questions(df: pd.DataFrame, max_questions: int, category_col: str = "intent_label") -> pd.DataFrame:
    """Limite le nombre de questions en gardant une distribution équilibrée par catégorie"""
    if len(df) <= max_questions:
        return df
    
    print(f"\n✂️ Limitation à {max_questions} questions...")
    
    # Calculer le quota par catégorie
    categories = df[category_col].value_counts()
    n_categories = len(categories)
    base_quota = max_questions // n_categories
    
    kept_indices = []
    
    # Prendre un quota de chaque catégorie
    for cat in categories.index:
        cat_df = df[df[category_col] == cat]
        # Prendre les questions avec le meilleur score de pertinence si disponible
        if 'relevance_score' in cat_df.columns:
            cat_df = cat_df.sort_values('relevance_score', ascending=False)
        quota = min(len(cat_df), base_quota + 1)  # +1 pour arrondi
        kept_indices.extend(cat_df.head(quota).index.tolist())
    
    # Si on dépasse, couper
    result = df.loc[kept_indices[:max_questions]].copy()
    print(f"   ✅ {len(result)} questions conservées")
    return result


def run_filter_pipeline(
    input_file: str,
    domain: str,
    max_questions: int = 100,
    similarity_threshold: float = 0.92,
    output_file: str = None
):
    """Pipeline complet de filtrage"""
    
    print("="*60, flush=True)
    print("🎯 FILTRAGE ET PERTINENCE DES QUESTIONS GEO", flush=True)
    print("="*60, flush=True)
    
    # Vérifications
    if not OPENAI_AVAILABLE:
        print("❌ OpenAI requis")
        return None
    
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_SECRET_KEY")
    if not api_key:
        print("❌ Clé API OpenAI non trouvée (OPENAI_API_KEY ou OPENAI_SECRET_KEY)")
        return None
    
    client = OpenAI(api_key=api_key)
    
    # Charger les données
    print(f"\n📂 Chargement: {input_file}")
    df = pd.read_csv(input_file)
    print(f"   ✅ {len(df)} questions chargées")
    
    # Détecter la colonne de questions (case-insensitive)
    question_col = None
    col_lower_map = {c.lower(): c for c in df.columns}
    for col in ['questions', 'prompt', 'question', 'raw_text', 'title']:
        if col in col_lower_map:
            question_col = col_lower_map[col]
            break
    
    if not question_col:
        print("❌ Aucune colonne de questions trouvée")
        return None
    
    # Renommer pour uniformité
    if question_col != 'question':
        df['question'] = df[question_col]
    
    # Détecter la colonne de catégorie (case-insensitive)
    category_col = None
    for col in ['intent_label', 'cluster_id', 'category', 'theme']:
        if col in col_lower_map:
            category_col = col_lower_map[col]
            break
    
    if not category_col:
        df['category'] = 'general'
        category_col = 'category'
    
    # 1. Analyser le domaine
    brand_context = analyze_domain(client, domain)
    
    # 2. Évaluer la pertinence
    print(f"\n📊 Évaluation de la pertinence pour {domain}...")
    questions = df['question'].tolist()
    relevance_results = evaluate_relevance_batch(client, questions, brand_context)
    
    # Ajouter les résultats au DataFrame
    relevance_map = {r['question']: r for r in relevance_results}
    df['is_relevant'] = df['question'].apply(lambda q: relevance_map.get(q, {}).get('is_relevant', True))
    df['relevance_score'] = df['question'].apply(lambda q: relevance_map.get(q, {}).get('relevance_score', 50))
    df['relevance_reason'] = df['question'].apply(lambda q: relevance_map.get(q, {}).get('reason', ''))
    
    # Filtrer par score de pertinence (>= 60)
    initial_count = len(df)
    min_score = 60
    df = df[df['relevance_score'] >= min_score].copy()
    print(f"   ✅ {initial_count - len(df)} questions avec score < {min_score} supprimées")
    print(f"   ✅ {len(df)} questions pertinentes conservées (score >= {min_score})")
    
    # Exclure les questions contenant des mots non pertinents pour le commerce
    excluded_words = ['gratuit', 'gratis', 'free', 'télécharger', 'download']
    before_exclusion = len(df)
    mask = ~df['question'].str.lower().str.contains('|'.join(excluded_words), na=False)
    df = df[mask].copy()
    excluded_count = before_exclusion - len(df)
    if excluded_count > 0:
        print(f"   ✅ {excluded_count} questions avec mots exclus ('gratuit', etc.) supprimées")
    
    # 3. Dédupliquer par similarité (première passe rapide)
    if SKLEARN_AVAILABLE and len(df) > 10:
        df = deduplicate_by_similarity(client, df, similarity_threshold)
    
    # 4. Déduplication intelligente par GPT (par catégorie)
    print("\n🧠 Déduplication intelligente par catégorie...")
    df = deduplicate_by_category(client, df, category_col)
    
    # 5. Limiter au nombre souhaité
    df = limit_questions(df, max_questions, category_col)
    
    # 5. Export
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"filtered_questions_{domain.lower().replace(' ', '_')}_{timestamp}.csv"
    
    df.to_csv(output_file, index=False)
    
    # Résumé
    print("\n" + "="*60)
    print("📊 RÉSUMÉ")
    print("="*60)
    print(f"   Domaine analysé: {domain}")
    print(f"   Questions initiales: {initial_count}")
    print(f"   Questions pertinentes: {len(df[df['is_relevant'] == True]) if 'is_relevant' in df.columns else len(df)}")
    print(f"   Questions finales: {len(df)}")
    print(f"\n📁 Export: {output_file}")
    print("\n✅ Filtrage terminé!")
    
    return output_file


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filtre et évalue la pertinence des questions GEO")
    parser.add_argument("input_file", help="Fichier CSV des questions (sortie étape 4)")
    parser.add_argument("domain", help="Domaine/marque à analyser (ex: 'Décathlon', 'student.be')")
    parser.add_argument("--max", type=int, default=100, help="Nombre max de questions à garder (défaut: 100)")
    parser.add_argument("--threshold", type=float, default=0.92, help="Seuil de similarité pour déduplication (défaut: 0.92)")
    parser.add_argument("--output", help="Fichier de sortie (optionnel)")
    
    args = parser.parse_args()
    
    run_filter_pipeline(
        input_file=args.input_file,
        domain=args.domain,
        max_questions=args.max,
        similarity_threshold=args.threshold,
        output_file=args.output
    )
