import csv
from io import StringIO
from pathlib import Path
from typing import Iterable, List, Tuple, Union

from models.raw_item import RawItem, SourceType


QUERY_COLUMNS = {"top queries", "query", "queries", "search query", "requête", "requêtes"}


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _rows(text: str) -> Tuple[List[str], Iterable[dict]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(StringIO(text), dialect=dialect)
    return reader.fieldnames or [], reader


def parse_gsc_content(content: bytes, min_words: int = 10, client_slug: str = "") -> List[RawItem]:
    fieldnames, rows = _rows(_decode(content))
    if not fieldnames:
        return []
    query_column = next((column for column in fieldnames if column.strip().casefold() in QUERY_COLUMNS), fieldnames[0])
    lookup = {column.strip().casefold(): column for column in fieldnames}
    clicks_column = lookup.get("clicks") or lookup.get("clics")
    impressions_column = lookup.get("impressions")
    items = []
    seen = set()
    for row in rows:
        query = str(row.get(query_column, "")).strip()
        normalized = " ".join(query.casefold().split())
        if len(query.split()) < min_words or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(RawItem(
            source_type=SourceType.GSC_CONVERSATION,
            platform="google_search_console",
            raw_text=query,
            url="https://search.google.com/search-console",
            title=query,
            metadata={
                "word_count": len(query.split()),
                "clicks": _number(row.get(clicks_column, 0)) if clicks_column else 0,
                "impressions": _number(row.get(impressions_column, 0)) if impressions_column else 0,
            },
            client_slug=client_slug,
        ))
    return items


def parse_gsc_file(path: Union[str, Path], min_words: int = 10, client_slug: str = "") -> List[RawItem]:
    return parse_gsc_content(Path(path).read_bytes(), min_words, client_slug)


def _number(value) -> int:
    text = str(value or "0").replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return int(float(text))
    except ValueError:
        return 0
