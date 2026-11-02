"""Qualification des questions : catégorie, thème kickoff, justification.

Quatre catégories, sans refonte du pipeline :
- ``brand`` : la question nomme la marque client ou un concurrent — voix de
  marque, jamais assimilée à une demande générique.
- ``comparaison_standard`` : intention comparative impliquant au moins une
  marque (client ou concurrent) — les « vs » standards du marché.
- ``non_brand_kickoff`` : question acheteuse sans marque qui correspond à un
  thème kickoff déclaré — le cœur du portefeuille (85 % cible).
- ``hors_périmètre`` : ni marque, ni comparaison de marque, ni thème kickoff.

Les questions ``proposed`` (générées pour compléter les comparaisons
standards) gardent leur provenance ``proposed`` : elles ne sont jamais
présentées comme collectées.
"""
import re
from typing import Dict, List, Optional, Sequence

COMPARATIVE_RE = re.compile(
    r"\b(vs\.?|versus|ou bien|différence entre|compar(?:er|é|atif|aison)|"
    r"meilleur(?:e|s)?|plutôt que|lequel|laquelle|lesquels|choisir)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "et", "de", "des", "du", "la", "le", "les", "en", "pour", "sans", "avec",
    "une", "un", "au", "aux", "the", "and", "for", "bien", "être", "etre",
}

# Mots trop génériques pour justifier à eux seuls une correspondance de thème
# (« gestion de projet » ≠ « gestion du stress »).
_GENERIC_TOKENS = {
    "gestion", "projet", "marché", "marche", "entreprise", "croissance",
    "stratégie", "strategie", "développement", "developpement", "produit",
    "produits", "conseil", "conseils", "solution", "solutions", "service",
    "services", "question", "besoin", "besoins", "choisir", "meilleur",
    "meilleure", "meilleurs", "outil", "outils", "formation", "avis",
}


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[\wÀ-ÿ]+", text.casefold()))


def _significant_tokens(text: str) -> List[str]:
    return [token for token in _norm(text).split() if len(token) >= 3 and token not in _STOPWORDS]


def _mentions_brand(normalized: str, variants: Sequence[str]) -> Optional[str]:
    for variant in variants:
        v = _norm(variant).replace(" ", "")
        if len(v) >= 4 and v in normalized.replace(" ", ""):
            return variant
    return None


def match_kickoff_theme(text: str, themes: Sequence[str]) -> Optional[str]:
    """Thème kickoff le plus proche.

    - correspondance par mot entier, avec tolérance au « s » final ;
    - un seul jeton ne suffit que s'il est distinctif (≥6 lettres) et non
      générique (« gestion », « projet » ne qualifient pas à eux seuls) ;
    - sinon, majorité des jetons du thème requise.
    """
    best, best_score = None, 0.0
    for theme in themes:
        tokens = _significant_tokens(theme)
        if not tokens:
            continue
        hits, distinctive_hits = 0, 0
        for token in tokens:
            base = token[:-1] if token.endswith("s") else token
            pattern = rf"(?<![\wÀ-ÿ]){re.escape(base)}s?(?![\wÀ-ÿ])"
            if re.search(pattern, text, re.IGNORECASE):
                hits += 1
                if len(token) >= 6 and token.casefold() not in _GENERIC_TOKENS:
                    distinctive_hits += 1
        score = hits / len(tokens)
        matched = score > 0.5 or (score > 0 and distinctive_hits > 0)
        if matched and score > best_score:
            best, best_score = theme, score
    return best


_INTERROGATIVE_RE = re.compile(r"\?|\b(quel(?:le|s)?|comment|pourquoi|combien|est-ce|où|quand|lequel|laquelle)\b", re.IGNORECASE)


def qualify_question(text: str, brand_variants: Sequence[str], competitors: Sequence[str], kickoff_themes: Sequence[str]) -> Dict[str, str]:
    normalized = _norm(text)
    brand_hit = _mentions_brand(normalized, brand_variants)
    competitor_hit = _mentions_brand(normalized, competitors)
    comparative = bool(COMPARATIVE_RE.search(text))
    interrogative = bool(_INTERROGATIVE_RE.search(text))
    theme = match_kickoff_theme(text, kickoff_themes)

    if comparative and (brand_hit or competitor_hit):
        which = brand_hit or competitor_hit
        return {"category": "comparaison_standard", "kickoff_theme": theme or "",
                "justification": f"comparaison impliquant « {which} »"}
    if comparative and theme:
        # « meilleur… vs alternatives » dans le périmètre kickoff : une
        # comparaison standard même sans marque citée (règle des 30).
        return {"category": "comparaison_standard", "kickoff_theme": theme,
                "justification": f"comparaison générique du périmètre « {theme} »"}
    if brand_hit and theme:
        return {"category": "brand", "kickoff_theme": theme,
                "justification": f"mentionne la marque « {brand_hit} » sur le thème « {theme} »"}
    if brand_hit and interrogative:
        return {"category": "brand", "kickoff_theme": "",
                "justification": f"question de marque « {brand_hit} » (sans thème kickoff)"}
    if brand_hit:
        return {"category": "hors_périmètre", "kickoff_theme": "",
                "justification": f"contenu de marque « {brand_hit} » hors kickoff et non interrogatif"}
    if theme:
        return {"category": "non_brand_kickoff", "kickoff_theme": theme,
                "justification": f"correspond au thème kickoff « {theme} »"}
    if competitor_hit:
        # Mention d'un concurrent sans intention comparative : famille
        # marque, pas comparaison — si c'est une vraie question.
        if interrogative:
            return {"category": "brand", "kickoff_theme": "",
                    "justification": f"question sur le concurrent « {competitor_hit} » (sans comparaison ni thème kickoff)"}
        return {"category": "hors_périmètre", "kickoff_theme": "",
                "justification": f"contenu concurrent « {competitor_hit} » hors kickoff et non interrogatif"}
    if not kickoff_themes:
        return {"category": "hors_périmètre", "kickoff_theme": "",
                "justification": "aucun thème kickoff déclaré — impossible de qualifier la pertinence"}
    return {"category": "hors_périmètre", "kickoff_theme": "",
            "justification": "ni marque, ni comparaison de marque, ni thème kickoff"}


def portfolio_quotas(target_size: int, brand_share: float = 0.15) -> Dict[str, int]:
    """Répartition cible : 15 % marque+comparaison, 85 % kickoff non-brand."""
    branded = int(round(target_size * brand_share))
    return {"brand_plus_comparaison": branded, "non_brand_kickoff": target_size - branded}


def select_with_quotas(candidates, sample_size: int, sample_fn, brand_share: float = 0.15, max_per_cluster: int = 5):
    """Sélection stratifiée par catégorie — stricte.

    - jamais plus de ``sample_size`` candidats, quel que soit l'arrondi des
      sous-quotas ;
    - pas de réallocation : une place non pourvue par une catégorie n'est pas
      comblée par une autre, le manque est reporté dans ``deficits`` ;
    - hors_périmètre et non qualifié ne sont jamais sélectionnés ;
    - les deux familles (brand, comparaison) se partagent le quota 15 %.

    ``sample_fn(group, size)`` applique la sélection stratifiée existante sur
    un sous-ensemble. Retourne (sélection, déficits par catégorie).
    """
    quotas = portfolio_quotas(sample_size, brand_share)
    seen_texts = set()
    unique = []
    for candidate in candidates:
        key = " ".join(candidate.text.casefold().split())
        if key in seen_texts:
            continue
        seen_texts.add(key)
        unique.append(candidate)
    groups = {
        "brand_plus_comparaison": [c for c in unique if c.metadata.get("qualification", {}).get("category") in ("brand", "comparaison_standard")],
        "non_brand_kickoff": [c for c in unique if c.metadata.get("qualification", {}).get("category") == "non_brand_kickoff"],
    }
    deficits = {}
    selected = []
    # Cœur kickoff d'abord : borné par son quota ET par la cible restante.
    kickoff_want = min(quotas["non_brand_kickoff"], sample_size - len(selected))
    kickoff_take = sample_fn(groups["non_brand_kickoff"], min(kickoff_want, len(groups["non_brand_kickoff"])), max_per_cluster)
    selected.extend(kickoff_take)
    deficits["non_brand_kickoff"] = max(0, quotas["non_brand_kickoff"] - len(kickoff_take))
    # Quota marque+comparaison borné par la cible restante. Chaque famille
    # prend d'abord sa moitié ; si l'une n'a pas assez de candidats, son solde
    # revient à l'autre famille — le quota 15 % lui-même n'est jamais dépassé.
    branded_want = min(quotas["brand_plus_comparaison"], sample_size - len(selected))
    half = branded_want - branded_want // 2
    unused = 0
    for family in ("comparaison_standard", "brand"):
        pool = [c for c in groups["brand_plus_comparaison"] if c.metadata.get("qualification", {}).get("category") == family]
        want = min(half + unused, branded_want - sum(1 for c in selected if c.metadata.get("qualification", {}).get("category") in ("brand", "comparaison_standard")), len(pool), sample_size - len(selected))
        take = sample_fn(pool, max(0, want), max_per_cluster)
        selected.extend(take)
        deficits[family] = max(0, half - len(take))
        unused += max(0, half - len(take))
    return selected[:sample_size], deficits
