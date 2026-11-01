"""Extraction de contenu depuis des URLs de forums / pages web.

Cascade d'extraction :
1. forumscraper (moteurs reconnus : phpBB, XenForo, SMF, vBulletin,
   Invision, StackExchange, Hacker News...) -> posts structurés.
2. trafilatura -> texte principal générique.
3. BeautifulSoup -> dernier recours (titre + body texte tronqué).

forumscraper requiert Python >= 3.10 ; il est importé paresseusement et
simplement ignoré s'il n'est pas installé/disponible.
"""

import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup


def extract_forum_thread(url: str, session: Optional[requests.Session] = None, logger=None) -> Optional[Dict[str, Any]]:
    """Essaie d'extraire un thread structuré via forumscraper.

    Retourne {"engine": str, "posts": [{"author", "date", "text"}], "title": str}
    ou None si le site n'est pas un moteur de forum reconnu."""
    try:
        from forumscraper import Extractor, Outputs  # type: ignore
    except Exception:
        return None
    try:
        extractor = Extractor()
        state: Dict[str, Any] = {}
        result = extractor.get_thread(url, state=state, output=Outputs.threads)
        threads = (state.get("data") or {}).get("threads") or result
        if isinstance(threads, dict):
            threads = [threads]
        if not threads:
            return None
        posts: List[Dict[str, Any]] = []
        title = ""
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            title = title or str(thread.get("title") or thread.get("name") or "")
            entries = thread.get("posts") or thread.get("messages") or [thread]
            for entry in entries if isinstance(entries, list) else [entries]:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("content") or entry.get("text") or entry.get("body") or entry.get("message") or "")
                text = re.sub(r"<[^>]+>", " ", text)
                text = " ".join(text.split())
                if len(text) < 20:
                    continue
                posts.append({
                    "author": str(entry.get("author") or entry.get("user") or ""),
                    "date": str(entry.get("date") or entry.get("time") or ""),
                    "text": text,
                })
        if not posts:
            return None
        engine = str(state.get("scraper") or getattr(extractor, "name", "") or "forumscraper")
        return {"engine": engine, "title": title, "posts": posts}
    except Exception as error:
        if logger:
            logger.debug(f"forumscraper failed on {url}: {error}")
        return None


def extract_page_text(url: str, session: Optional[requests.Session] = None,
                      timeout: int = 30, logger=None) -> Optional[Dict[str, Any]]:
    """Extrait le texte principal d'une page via trafilatura.

    Retourne {"title": str, "text": str, "date": str} ou None."""
    try:
        import trafilatura  # type: ignore
    except ImportError:
        return _extract_page_bs4(url, session, timeout, logger)
    try:
        fetcher = session.get if session else requests.get
        response = fetcher(url, timeout=timeout)
        if not response.ok:
            return None
        extracted = trafilatura.extract(
            response.text,
            include_comments=True,
            include_tables=False,
            with_metadata=True,
            output_format="json",
            url=url,
        )
        if not extracted:
            return None
        import json
        data = json.loads(extracted) if isinstance(extracted, str) else extracted
        text = (data.get("text") or "").strip()
        if len(text) < 40:
            return _extract_page_bs4(url, session, timeout, logger)
        return {
            "title": str(data.get("title") or ""),
            "text": text,
            "date": str(data.get("date") or ""),
        }
    except Exception as error:
        if logger:
            logger.debug(f"trafilatura failed on {url}: {error}")
        return _extract_page_bs4(url, session, timeout, logger)


def _extract_page_bs4(url: str, session: Optional[requests.Session],
                      timeout: int, logger=None) -> Optional[Dict[str, Any]]:
    """Fallback minimaliste BeautifulSoup."""
    try:
        fetcher = session.get if session else requests.get
        response = fetcher(url, timeout=timeout)
        if not response.ok:
            return None
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        title = soup.title.get_text(strip=True) if soup.title else ""
        text = " ".join(soup.get_text(" ").split())[:10000]
        if len(text) < 40:
            return None
        return {"title": title, "text": text, "date": ""}
    except Exception as error:
        if logger:
            logger.debug(f"BeautifulSoup extraction failed on {url}: {error}")
        return None


def extract_url_content(url: str, session: Optional[requests.Session] = None,
                        timeout: int = 30, logger=None) -> Optional[Dict[str, Any]]:
    """Cascade complète : forumscraper -> trafilatura -> BeautifulSoup.

    Retourne {"engine", "title", "posts" OU "text", "date"}."""
    thread = extract_forum_thread(url, session, logger)
    if thread and thread.get("posts"):
        return thread
    page = extract_page_text(url, session, timeout, logger)
    if page:
        page["engine"] = "trafilatura"
        return page
    return None
