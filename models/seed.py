from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List


class SeedType(str, Enum):
    KEYWORD = "keyword"
    THEME = "theme"
    BRAND = "brand"
    COMPETITOR = "competitor"
    PRODUCT = "product"
    PROBLEM = "problem"


@dataclass(frozen=True)
class Seed:
    value: str
    seed_type: SeedType = SeedType.KEYWORD
    priority: int = 50
    language: str = "fr"
    market: str = "FR"
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Dict, language: str = "fr", market: str = "FR") -> "Seed":
        return cls(
            value=str(data.get("value", "")).strip(),
            seed_type=SeedType(data.get("type", "keyword")),
            priority=max(0, min(100, int(data.get("priority", 50)))),
            language=str(data.get("language", language)),
            market=str(data.get("market", market)),
            enabled=bool(data.get("enabled", True)),
        )


def deduplicate_seeds(seeds: Iterable[Seed]) -> List[Seed]:
    selected = {}
    for seed in seeds:
        key = (seed.value.casefold().strip(), seed.seed_type.value, seed.language, seed.market)
        if not key[0]:
            continue
        existing = selected.get(key)
        if existing is None or seed.priority > existing.priority:
            selected[key] = seed
    return sorted(selected.values(), key=lambda seed: (-seed.priority, seed.seed_type.value, seed.value.casefold()))
