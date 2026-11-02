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
    r"meilleur(?:e|s)? que|plutôt que|lequel|laquelle|lesquels|choisir entre)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "et", "de", "des", "du", "la", "le", "les", "en", "pour", "sans", "avec",
    "une", "un", "au", "aux", "the", "and", "for", "bien", "être", "etre",
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
    """Thème kickoff le plus proche : majorité des jetons significatifs du
    thème présents dans la question, ou jeton distinctif unique (≥7 lettres)."""
    normalized = _norm(text)
    best, best_score = None, 0.0
    for theme in themes:
        tokens = _significant_tokens(theme)
        if not tokens:
            continue
        hits = sum(1 for token in tokens if token in normalized)
        distinctive = any(len(token) >= 7 and token in normalized for token in tokens)
        score = hits / len(tokens)
        if (score >= 0.5 or distinctive) and score > best_score:
            best, best_score = theme, score
    return best


def qualify_question(text: str, brand_variants: Sequence[str], competitors: Sequence[str], kickoff_themes: Sequence[str]) -> Dict[str, str]:
    normalized = _norm(text)
    brand_hit = _mentions_brand(normalized, brand_variants)
    competitor_hit = _mentions_brand(normalized, competitors)
    comparative = bool(COMPARATIVE_RE.search(text))
    theme = match_kickoff_theme(text, kickoff_themes)

    if comparative and (brand_hit or competitor_hit):
        which = brand_hit or competitor_hit
        return {"category": "comparaison_standard", "kickoff_theme": theme or "",
                "justification": f"comparaison impliquant « {which} »"}
    if brand_hit:
        return {"category": "brand", "kickoff_theme": theme or "",
                "justification": f"mentionne la marque « {brand_hit} »"}
    if theme:
        return {"category": "non_brand_kickoff", "kickoff_theme": theme,
                "justification": f"correspond au thème kickoff « {theme} »"}
    if competitor_hit:
        return {"category": "comparaison_standard", "kickoff_theme": theme or "",
                "justification": f"mentionne le concurrent « {competitor_hit} »"}
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
    groups = {
        "brand_plus_comparaison": [c for c in candidates if c.metadata.get("qualification", {}).get("category") in ("brand", "comparaison_standard")],
        "non_brand_kickoff": [c for c in candidates if c.metadata.get("qualification", {}).get("category") == "non_brand_kickoff"],
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
