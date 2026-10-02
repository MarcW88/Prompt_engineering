from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from models.seed import Seed, SeedType, deduplicate_seeds


@dataclass(frozen=True)
class PlannedQuery:
    query: str
    seed: str
    seed_type: str
    priority: int
    source: str


SOURCE_TYPES: Dict[str, Sequence[SeedType]] = {
    "reddit": (SeedType.KEYWORD, SeedType.PROBLEM, SeedType.PRODUCT, SeedType.THEME, SeedType.BRAND, SeedType.COMPETITOR),
    "forum": (SeedType.KEYWORD, SeedType.PROBLEM, SeedType.PRODUCT, SeedType.THEME, SeedType.BRAND, SeedType.COMPETITOR),
    "serp": (SeedType.KEYWORD, SeedType.PROBLEM, SeedType.PRODUCT, SeedType.THEME, SeedType.BRAND, SeedType.COMPETITOR),
}


def plan_queries(seeds: Iterable[Seed], source: str, budget: int, domain: str = "") -> List[PlannedQuery]:
    accepted = SOURCE_TYPES.get(source, SOURCE_TYPES["serp"])
    selected = [seed for seed in deduplicate_seeds(seeds) if seed.enabled and seed.seed_type in accepted]
    planned = []
    seen = set()
    for seed in selected:
        query = f"site:{domain} {seed.value}" if source == "forum" and domain else seed.value
        normalized = query.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        planned.append(PlannedQuery(query, seed.value, seed.seed_type.value, seed.priority, source))
        if len(planned) >= max(0, budget):
            break
    return planned


def expand_serp_templates(seeds: Iterable[Seed], templates: Iterable[str], budget: int, brand_name: str = "") -> List[PlannedQuery]:
    selected = deduplicate_seeds(seed for seed in seeds if seed.enabled)
    by_type = {seed_type: [seed for seed in selected if seed.seed_type == seed_type] for seed_type in SeedType}
    planned = []
    seen = set()
    for template in templates:
        base_seeds = by_type[SeedType.KEYWORD] + by_type[SeedType.PRODUCT] + by_type[SeedType.THEME] + by_type[SeedType.PROBLEM]
        for base in base_seeds or selected:
            brands = by_type[SeedType.BRAND] or [None]
            competitors = by_type[SeedType.COMPETITOR] or [None]
            for brand in brands:
                for competitor in competitors:
                    query = template.replace("{seed}", base.value).replace("{theme}", base.value)
                    query = query.replace("{brand}", brand_name or (brand.value if brand else ""))
                    query = query.replace("{brand_variant}", brand.value if brand else "").replace("{competitor}", competitor.value if competitor else "")
                    query = " ".join(query.split()).strip()
                    if not query or "{" in query or query.casefold() in seen:
                        continue
                    seen.add(query.casefold())
                    priority = max(base.priority, brand.priority if brand else 0, competitor.priority if competitor else 0)
                    planned.append(PlannedQuery(query, base.value, base.seed_type.value, priority, "serp"))
                    if len(planned) >= max(0, budget):
                        return planned
    return planned
