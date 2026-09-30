"""
Normalisation Sémantique des Questions GEO
Pipeline en 4 niveaux pour préparer le dataset au ML/monitoring

Niveaux:
1. Normalisation formelle (doublons exacts, casse, ponctuation)
2. Déduplication sémantique (embeddings + clustering)
3. Canonicalisation GEO (1 question canonique + variantes)
4. Tagging analytique (intention, sensibilité, contexte)
"""

import os
import re
import json
import hashlib
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# ============================================
# NIVEAU 1: NORMALISATION FORMELLE
# ============================================

# Corrections de coquilles courantes (extensible)
TYPO_CORRECTIONS = {
    # Molécules/compléments
    r'\bl[- ]?lyrosine\b': 'L-tyrosine',
    r'\bl[- ]?glutamin\b': 'L-glutamine',
    r'\bglutamin\b': 'glutamine',
    r'\bcreatine\b': 'créatine',
    r'\bproteines?\b': 'protéines',
    r'\bvitamines?\s+d\b': 'vitamine D',
    r'\bomega\s*3\b': 'oméga-3',
    r'\bomega\s*6\b': 'oméga-6',
    r'\bmagnesium\b': 'magnésium',
    r'\bcalcium\b': 'calcium',
    r'\bmelatonine\b': 'mélatonine',
    r'\bmillepertui\b': 'millepertuis',
    # Termes médicaux
    r'\beffets?\s+secondaires?\b': 'effets secondaires',
    r'\bcontre[- ]?indications?\b': 'contre-indications',
    r'\binterractions?\b': 'interactions',
    # Formulations
    r'\best[- ]?ce\s+que\b': 'est-ce que',
    r'\bqu\'est[- ]?ce\s+que\b': "qu'est-ce que",
    r'\bpourquoi\s+est[- ]?ce\b': 'pourquoi est-ce',
}


def normalize_text_formal(text: str) -> str:
    """Niveau 1: Normalisation formelle sans toucher au sens"""
    if not text or not isinstance(text, str):
        return ""
    
    # Trim et normalisation des espaces
    text = ' '.join(text.split())
    
    # Correction des coquilles
    for pattern, replacement in TYPO_CORRECTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # Normalisation de la ponctuation
    text = re.sub(r'\s+([?!.,;:])', r'\1', text)  # Pas d'espace avant ponctuation
    text = re.sub(r'([?!])+', r'\1', text)  # Pas de ponctuation répétée
    text = re.sub(r'\.{2,}', '...', text)  # Normaliser les points de suspension
    
    # S'assurer que la question finit par ?
    text = text.strip()
    if text and not text.endswith('?') and not text.endswith('!') and not text.endswith('.'):
        # Vérifier si c'est une question
        question_starters = ['comment', 'pourquoi', 'quand', 'où', 'qui', 'que', 'quel', 
                            'quelle', 'quels', 'quelles', 'est-ce', "qu'est", 'combien',
                            'lequel', 'laquelle', 'lesquels', 'lesquelles', 'peut-on',
                            'faut-il', 'doit-on', 'y a-t-il', 'existe-t-il']
        if any(text.lower().startswith(q) for q in question_starters):
            text += ' ?'
    
    return text


def get_text_hash(text: str) -> str:
    """Génère un hash pour détecter les doublons exacts"""
    normalized = text.lower().strip()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = ' '.join(normalized.split())
    return hashlib.md5(normalized.encode()).hexdigest()


def deduplicate_exact(df: pd.DataFrame, text_column: str = 'question') -> pd.DataFrame:
    """Supprime les doublons exacts (après normalisation)"""
    df = df.copy()
    df['_normalized'] = df[text_column].apply(normalize_text_formal)
    df['_hash'] = df['_normalized'].apply(get_text_hash)
    
    # Garder la première occurrence de chaque hash
    df_dedup = df.drop_duplicates(subset='_hash', keep='first')
    
    removed = len(df) - len(df_dedup)
    print(f"   ✅ {removed} doublons exacts supprimés")
    
    # Nettoyer les colonnes temporaires
    df_dedup = df_dedup.drop(columns=['_hash'])
    df_dedup[text_column] = df_dedup['_normalized']
    df_dedup = df_dedup.drop(columns=['_normalized'])
    
    return df_dedup.reset_index(drop=True)


# ============================================
# NIVEAU 2: DÉDUPLICATION SÉMANTIQUE
# ============================================

def get_embeddings(client: OpenAI, texts: List[str], batch_size: int = 100) -> np.ndarray:
    """Obtient les embeddings via OpenAI"""
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        print(f"   Embeddings batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}...")
        
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch
        )
        
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
    
    return np.array(all_embeddings)


def cluster_by_semantic_similarity(
    df: pd.DataFrame, 
    embeddings: np.ndarray,
    similarity_threshold: float = 0.85
) -> pd.DataFrame:
    """Regroupe les questions par similarité sémantique"""
    
    if not SKLEARN_AVAILABLE:
        print("   ⚠️ sklearn non disponible, clustering ignoré")
        df['intent_id'] = [f"INT_{i:04d}" for i in range(len(df))]
        return df
    
    # Calculer la matrice de distance (1 - similarité cosinus)
    similarity_matrix = cosine_similarity(embeddings)
    distance_matrix = 1 - similarity_matrix
    
    # Clustering hiérarchique
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1 - similarity_threshold,
        metric='precomputed',
        linkage='average'
    )
    
    labels = clustering.fit_predict(distance_matrix)
    
    # Assigner les intent_id
    df = df.copy()
    df['intent_id'] = [f"INT_{label:04d}" for label in labels]
    
    n_clusters = len(set(labels))
    print(f"   ✅ {n_clusters} groupes d'intention identifiés")
    
    return df


# ============================================
# NIVEAU 3: CANONICALISATION GEO
# ============================================

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


def canonicalize_intent_group(
    client: OpenAI, 
    questions: List[str],
    intent_id: str
) -> Dict:
    """Canonicalise un groupe de questions similaires"""
    
    if len(questions) == 1:
        return {
            "intent_id": intent_id,
            "intent_summary": "",
            "canonical_question": questions[0],
            "variants": [],
            "confidence": 1.0
        }
    
    # Limiter à 10 questions pour le prompt
    sample = questions[:10] if len(questions) > 10 else questions
    questions_text = "\n".join([f"- {q}" for q in sample])
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CANONICALIZATION_PROMPT},
                {"role": "user", "content": f"Groupe de questions (intent_id: {intent_id}):\n\n{questions_text}"}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parser le JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        result = json.loads(content)
        result["intent_id"] = intent_id
        return result
        
    except Exception as e:
        print(f"   ⚠️ Erreur canonicalisation {intent_id}: {str(e)[:50]}")
        return {
            "intent_id": intent_id,
            "intent_summary": "",
            "canonical_question": questions[0],
            "variants": questions[1:5] if len(questions) > 1 else [],
            "confidence": 0.5
        }


# ============================================
# NIVEAU 4: TAGGING ANALYTIQUE
# ============================================

TAGGING_PROMPT = """Tu es un expert en classification de questions pour l'analyse GEO.

Analyse cette question et fournis les tags suivants:

1. **intent_type**: Le type d'intention
   - information: cherche à comprendre/apprendre
   - decision: aide à choisir/décider
   - comparison: compare des options
   - safety: préoccupation santé/sécurité/risque
   - howto: cherche une méthode/procédure
   - validation: cherche confirmation

2. **sensitivity**: Niveau de sensibilité
   - low: sujet général
   - medium: santé générale, bien-être
   - high: médicaments, interactions, pathologies

3. **domain**: Domaine principal
   - nutrition, sport, santé, beauté, médical, général

4. **entities**: Liste des entités mentionnées (produits, molécules, marques)

5. **context**: Contexte d'usage si détectable
   - sport, grossesse, enfant, senior, pathologie, général

Réponds en JSON compact:
{"intent_type": "...", "sensitivity": "...", "domain": "...", "entities": [...], "context": "..."}"""


def tag_question(client: OpenAI, question: str) -> Dict:
    """Ajoute des tags analytiques à une question"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": TAGGING_PROMPT},
                {"role": "user", "content": question}
            ],
            temperature=0.2,
            max_tokens=200
        )
        
        content = response.choices[0].message.content.strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        return json.loads(content)
        
    except Exception as e:
        return {
            "intent_type": "information",
            "sensitivity": "medium",
            "domain": "général",
            "entities": [],
            "context": "général"
        }


def tag_questions_batch(
    client: OpenAI, 
    df: pd.DataFrame,
    question_column: str = 'canonical_question'
) -> pd.DataFrame:
    """Tag toutes les questions canoniques"""
    
    df = df.copy()
    tags_list = []
    
    unique_questions = df[question_column].unique()
    print(f"   Tagging {len(unique_questions)} questions uniques...")
    
    for i, question in enumerate(unique_questions):
        if (i + 1) % 20 == 0:
            print(f"   [{i+1}/{len(unique_questions)}]...")
        
        tags = tag_question(client, question)
        tags['question'] = question
        tags_list.append(tags)
    
    # Créer un mapping question -> tags
    tags_df = pd.DataFrame(tags_list)
    
    # Merger avec le df original
    df = df.merge(tags_df, left_on=question_column, right_on='question', how='left')
    df = df.drop(columns=['question'], errors='ignore')
    
    return df


# ============================================
# PIPELINE PRINCIPAL
# ============================================

def run_normalization_pipeline(
    input_file: str,
    output_file: str = None,
    openai_api_key: str = None,
    text_column: str = 'raw_text',
    similarity_threshold: float = 0.85,
    run_tagging: bool = True
) -> pd.DataFrame:
    """
    Pipeline complet de normalisation en 4 niveaux
    
    Args:
        input_file: Chemin du CSV d'entrée
        output_file: Chemin du CSV de sortie (auto-généré si None)
        openai_api_key: Clé API OpenAI (ou variable d'env)
        text_column: Colonne contenant les questions
        similarity_threshold: Seuil de similarité pour le clustering (0.8-0.95)
        run_tagging: Exécuter le niveau 4 (tagging analytique)
    
    Returns:
        DataFrame normalisé avec intent_id, canonical_question, tags
    """
    
    print("\n" + "="*60)
    print("🔄 NORMALISATION SÉMANTIQUE DES QUESTIONS GEO")
    print("="*60)
    
    # Vérifier les dépendances
    if not OPENAI_AVAILABLE:
        raise ImportError("OpenAI non installé. Exécutez: pip install openai")
    
    if not SKLEARN_AVAILABLE:
        print("⚠️ sklearn non installé. Le clustering sera limité.")
    
    # Clé API
    api_key = openai_api_key or os.getenv("OPENAI_SECRET_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Clé API OpenAI non trouvée")
    
    client = OpenAI(api_key=api_key)
    
    # Charger les données
    print(f"\n📂 Chargement de {input_file}...")
    df = pd.read_csv(input_file)
    print(f"   ✅ {len(df)} lignes chargées")
    
    # Vérifier la colonne
    if text_column not in df.columns:
        # Essayer des alternatives
        alternatives = ['question', 'title', 'text', 'raw_text']
        for alt in alternatives:
            if alt in df.columns:
                text_column = alt
                break
        else:
            raise ValueError(f"Colonne '{text_column}' non trouvée. Colonnes disponibles: {list(df.columns)}")
    
    print(f"   Colonne utilisée: '{text_column}'")
    
    # ========================================
    # NIVEAU 1: Normalisation formelle
    # ========================================
    print(f"\n🧱 NIVEAU 1: Normalisation formelle")
    df = deduplicate_exact(df, text_column)
    print(f"   📊 {len(df)} questions après déduplication")
    
    # ========================================
    # NIVEAU 2: Déduplication sémantique
    # ========================================
    print(f"\n🧱 NIVEAU 2: Déduplication sémantique")
    
    questions = df[text_column].tolist()
    print(f"   Calcul des embeddings pour {len(questions)} questions...")
    embeddings = get_embeddings(client, questions)
    
    df = cluster_by_semantic_similarity(df, embeddings, similarity_threshold)
    
    # Stats par cluster
    cluster_sizes = df['intent_id'].value_counts()
    print(f"   📊 Taille moyenne des groupes: {cluster_sizes.mean():.1f}")
    print(f"   📊 Plus grand groupe: {cluster_sizes.max()} questions")
    
    # ========================================
    # NIVEAU 3: Canonicalisation GEO
    # ========================================
    print(f"\n🧱 NIVEAU 3: Canonicalisation GEO")
    
    canonical_results = []
    intent_groups = df.groupby('intent_id')[text_column].apply(list).to_dict()
    
    print(f"   Canonicalisation de {len(intent_groups)} groupes...")
    for i, (intent_id, questions) in enumerate(intent_groups.items()):
        if (i + 1) % 20 == 0:
            print(f"   [{i+1}/{len(intent_groups)}]...")
        
        result = canonicalize_intent_group(client, questions, intent_id)
        canonical_results.append(result)
    
    # Créer le DataFrame des canoniques
    canonical_df = pd.DataFrame(canonical_results)
    
    # Merger avec les données originales
    df = df.merge(
        canonical_df[['intent_id', 'intent_summary', 'canonical_question', 'confidence']], 
        on='intent_id', 
        how='left'
    )
    
    print(f"   ✅ {len(canonical_df)} questions canoniques générées")
    
    # ========================================
    # NIVEAU 4: Tagging analytique (optionnel)
    # ========================================
    if run_tagging:
        print(f"\n🧱 NIVEAU 4: Tagging analytique")
        df = tag_questions_batch(client, df, 'canonical_question')
        print(f"   ✅ Tagging terminé")
    
    # ========================================
    # Export
    # ========================================
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f"{base_name}_normalized_{timestamp}.csv"
    
    df.to_csv(output_file, index=False)
    
    # Export des canoniques uniquement
    canonical_output = output_file.replace('.csv', '_canonical.csv')
    canonical_export = canonical_df.copy()
    if run_tagging:
        # Ajouter les tags aux canoniques
        tags_subset = df[['intent_id', 'intent_type', 'sensitivity', 'domain', 'context']].drop_duplicates()
        canonical_export = canonical_export.merge(tags_subset, on='intent_id', how='left')
    
    canonical_export.to_csv(canonical_output, index=False)
    
    # ========================================
    # Résumé
    # ========================================
    print(f"\n" + "="*60)
    print(f"📊 RÉSUMÉ DE LA NORMALISATION")
    print(f"="*60)
    print(f"   Questions initiales: {len(pd.read_csv(input_file))}")
    print(f"   Après dédup exacte: {len(df)}")
    print(f"   Groupes d'intention: {len(canonical_df)}")
    print(f"   Réduction: {100 * (1 - len(canonical_df)/len(df)):.1f}%")
    
    if run_tagging and 'intent_type' in df.columns:
        print(f"\n   Distribution des intentions:")
        for intent_type, count in df['intent_type'].value_counts().head(5).items():
            print(f"      - {intent_type}: {count}")
    
    print(f"\n📁 Exports:")
    print(f"   - Complet: {output_file}")
    print(f"   - Canoniques: {canonical_output}")
    print("="*60 + "\n")
    
    return df


# ============================================
# CLI
# ============================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python normalize_questions.py <input_csv> [output_csv] [--no-tagging]")
        print("\nExemple:")
        print("  python normalize_questions.py lepivits_questions.csv")
        print("  python normalize_questions.py lepivits_questions.csv output.csv --no-tagging")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None
    run_tagging = '--no-tagging' not in sys.argv
    
    run_normalization_pipeline(
        input_file=input_file,
        output_file=output_file,
        run_tagging=run_tagging
    )
