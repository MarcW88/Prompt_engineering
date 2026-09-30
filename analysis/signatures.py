import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Set


@dataclass(frozen=True)
class FanOutSignature:
    queries: List[str]
    normalized_queries: List[str]
    tokens: Set[str]


def normalize_query(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def build_signature(queries: Iterable[str]) -> FanOutSignature:
    unique = []
    seen = set()
    for query in queries:
        normalized = normalize_query(query)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append((query.strip(), normalized))
    return FanOutSignature(
        queries=[query for query, _ in unique],
        normalized_queries=[normalized for _, normalized in unique],
        tokens={token for _, normalized in unique for token in normalized.split()},
    )


def query_similarity(left: str, right: str) -> float:
    left_tokens = set(normalize_query(left).split())
    right_tokens = set(normalize_query(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def signature_similarity(left: FanOutSignature, right: FanOutSignature) -> float:
    if not left.normalized_queries or not right.normalized_queries:
        return 0.0
    forward = [max(query_similarity(query, candidate) for candidate in right.queries) for query in left.queries]
    backward = [max(query_similarity(query, candidate) for candidate in left.queries) for query in right.queries]
    return (sum(forward) / len(forward) + sum(backward) / len(backward)) / 2
