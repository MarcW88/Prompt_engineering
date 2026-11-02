"""Adaptateur des modules onboarding d'Elmo.

Source : https://github.com/elmohq/elmo — commit figé
aa624102b06c9f7e2f7deb8d99bd3aa62077c54d (2026-11-02), licence MIT
(copyright Blue Whale Software, LLC — voir LICENSE.md du dépôt source).

Fichiers portés :
- packages/lib/src/onboarding/utils.ts  → clean_url, clean_domain,
  infer_brand_name, unique_lower, unique_trim, dedupe_key
- packages/lib/src/onboarding/analyze.ts → TAG_GUIDANCE, prompt_mix_guidance,
  website_excerpt_block, normalize_prompts (dédup + tags kebab-case)
- packages/lib/src/onboarding/suggest-prompts.ts → build_suggest_prompt
  (complément d'angles manquants, anti-variantes triviales)

Non repris : llm.ts (routage multi-providers TypeScript/Zod → remplacé par
notre appel OpenAI structuré existant), wholeWordPattern/getWebsiteExcerpt
(dépendances internes d'un autre package).

Adaptations : passage en Python ; les fragments courts d'Elmo restent possibles
mais le schéma de sortie accepte aussi questions complètes et demandes
contextualisées (consigne du cahier des charges) ; pas de persona systématique.
"""
import re
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse, urlunparse

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

TAG_GUIDANCE = (
    "Tags tailored to this brand and prompt set: describe WHAT the prompt is about "
    "(product category, audience, sub-feature, competitor), not the answer's goal. "
    "Prefer single-word tags; max 5 distinct values across all prompts; attach a tag "
    "only if it discriminates this prompt from the others."
)


def clean_url(raw: str) -> str:
    """Elmo cleanUrl : normalise sans retirer path/query, retire les credentials."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I) and not re.match(r"^https?://", raw, re.I):
        return ""
    try:
        url = urlparse(raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}")
        if not url.hostname or url.scheme not in ("http", "https"):
            return ""
        netloc = url.hostname + (f":{url.port}" if url.port else "")
        return urlunparse((url.scheme, netloc, url.path, url.params, url.query, url.fragment))
    except ValueError:
        return ""


def clean_domain(raw: str) -> str:
    """Elmo cleanDomain : hostname en minuscules, sans www."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        url = urlparse(raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}")
        return (url.hostname or "").lower().removeprefix("www.")
    except ValueError:
        return re.sub(r"^www\.", "", re.sub(r"^https?://", "", raw).split("/")[0].lower())


def clean_and_validate_domain(raw: str) -> Optional[str]:
    domain = clean_domain(raw)
    return domain if domain and _DOMAIN_RE.match(domain) else None


def infer_brand_name(website: str) -> str:
    domain = clean_domain(website)
    return (domain.split(".")[0] or domain).capitalize() if domain else website


def dedupe_key(value: str) -> str:
    """Elmo dedupeKey : trim + espaces uniques + minuscules."""
    return re.sub(r"\s+", " ", value.strip()).lower()


def unique_lower(values: Sequence[str]) -> List[str]:
    seen, out = set(), []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def unique_trim(values: Sequence[str]) -> List[str]:
    seen, out = set(), []
    for value in values:
        trimmed = value.strip()
        if trimmed and trimmed.lower() not in seen:
            seen.add(trimmed.lower())
            out.append(trimmed)
    return out


def prompt_mix_guidance(branded_share: str) -> str:
    """Elmo promptMixGuidance : majorité de requêtes non-brand."""
    return (
        f"IMPORTANT: the MAJORITY must be UNBRANDED — generic category/persona queries "
        f'that do NOT contain the brand name (e.g. "best [category]", "best [category] for '
        f'[persona]", "[category] vs alternatives", "where to buy [category]"). '
        f"{branded_share} should be branded (contain the brand name). The goal is to test "
        f"whether AI models mention the brand organically in response to unbranded queries."
    )


def website_excerpt_block(url: str, excerpt: str) -> str:
    return f"\nText from {url}:\n---\n{excerpt}\n---\n" if excerpt else ""


def build_suggest_prompt(
    *, analysis_url: str, brand_name: str, website_excerpt: str,
    existing_prompts: Sequence[str], existing_tags: Sequence[str],
    competitors: Sequence[str], count: int, language: str = "fr",
    kickoff_context: str = "",
) -> str:
    """Elmo buildPrompt (suggest-prompts) adapté : couverture des angles
    manquants du kickoff, variantes triviales interdites."""
    excerpt_block = website_excerpt_block(analysis_url, website_excerpt)
    competitors_line = f"\nCompetitors already tracked: {', '.join(competitors)}\n" if competitors else ""
    tags_line = (
        f"\nTags already in use (reuse these where they fit): {', '.join(existing_tags)}\n"
        if existing_tags else ""
    )
    kickoff_block = f"\nClient kickoff context (must be respected — do not propose outside it):\n{kickoff_context}\n" if kickoff_context else ""
    existing_block = (
        "\nPrompts the brand already has — do NOT repeat these, reword them, or return "
        "trivial variants (plurals, reordered words, swapped synonyms):\n"
        + "\n".join(f"- {p}" for p in existing_prompts) + "\n"
        if existing_prompts else ""
    )
    return (
        f"Suggest {count} more AI tracking prompts for {brand_name} ({analysis_url}), "
        f"in {language}.\n{excerpt_block}{competitors_line}{tags_line}{kickoff_block}{existing_block}\n"
        f"Each prompt is something a real person would type into ChatGPT where an answer "
        f"could plausibly mention {brand_name} or its competitors — a full question, a "
        f"contextualized request, or a short search-style fragment. Cover angles the "
        f"existing prompts miss: other product categories, audiences, use cases, price "
        f"points, regions, or buying stages. {prompt_mix_guidance('At most a quarter')}"
    )


def to_kebab(tag: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", tag.strip().lower()))


def normalize_prompts(raw_items: Sequence[Dict], max_prompts: int, existing: Optional[set] = None) -> List[Dict]:
    """Elmo normalizePrompts : dédup par texte normalisé + tags kebab (≤3)."""
    seen = set(existing or set())
    out = []
    for item in raw_items or []:
        if len(out) >= max_prompts:
            break
        text = dedupe_key(str(item.get("prompt", "")))
        if not text or text in seen:
            continue
        seen.add(text)
        out.append({"prompt": text, "tags": unique_lower([to_kebab(t) for t in item.get("tags", []) if to_kebab(t)])[:3]})
    return out
