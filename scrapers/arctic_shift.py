"""Client minimal pour l'API Arctic Shift (archive Reddit publique).

Arctic Shift permet de rechercher des posts/commentaires Reddit historiques
sans clé API, ce qui remplace l'usage de l'endpoint `.json` de Reddit
(rate-limité, recherche limitée) et de Bright Data pour cette source.

Docs : https://github.com/ArthurHeitmann/arctic_shift
"""

import time
from typing import Any, Dict, List, Optional

import requests


class ArcticShiftClient:
    base_url = "https://arctic-shift.photon-reddit.com/api"

    def __init__(self, delay: float = 1.0, timeout: int = 30, logger=None):
        self.delay = delay
        self.timeout = timeout
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PromptFinder/1.0 (question research; contact: self-hosted)",
            "Accept": "application/json",
        })
        self.available: Optional[bool] = None

    def _get(self, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            time.sleep(self.delay)
            params = {k: v for k, v in params.items() if v not in (None, "")}
            for attempt in range(3):
                response = self.session.get(url, params=params, timeout=self.timeout)
                # 429 et 422 "Timeout. Maybe slow down" = throttling côté archive :
                # attendre puis retenter plutôt que de déclarer l'API indisponible.
                if response.status_code == 429 or (response.status_code == 422 and "slow down" in response.text):
                    wait = 30 if response.status_code == 429 else 10 * (attempt + 1)
                    if self.logger:
                        self.logger.warning(f"Arctic Shift throttled ({response.status_code}), waiting {wait}s")
                    time.sleep(wait)
                    continue
                break
            response.raise_for_status()
            payload = response.json()
            self.available = True
        except requests.HTTPError as error:
            # Une erreur 4xx définitive signale un problème de requête, pas une
            # indisponibilité du service : fallback local sans abaisser available.
            status = error.response.status_code if error.response is not None else 0
            if status and status < 500:
                if self.logger:
                    self.logger.warning(f"Arctic Shift rejected the query ({status}); skipping")
                return []
            self.available = False
            if self.logger:
                self.logger.warning(f"Arctic Shift unavailable ({error}); falling back")
            return []
        except Exception as error:
            self.available = False
            if self.logger:
                self.logger.warning(f"Arctic Shift unavailable ({error}); falling back")
            return []
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return [record for record in data if isinstance(record, dict)]
            return [payload]
        if isinstance(payload, list):
            return [record for record in payload if isinstance(record, dict)]
        return []

    def search_posts(self, subreddit: str, query: str = "", limit: int = 25,
                     after: str = "", before: str = "") -> List[Dict[str, Any]]:
        """Recherche des posts dans un subreddit.

        Args:
            subreddit: nom du subreddit (sans r/).
            query: requête full-text (peut être vide pour lister les posts récents).
            limit: nombre max de posts (API plafonnée autour de 100).
            after/before: bornes temporelles (ex: "2025-01-01" ou timestamp).
        """
        # API réelle : combiner `query` et `sort` renvoie 422 (scan trop lourd) ;
        # avec une requête on laisse le tri par défaut.
        params = {"subreddit": subreddit, "query": query, "limit": max(1, min(int(limit), 100)), "after": after, "before": before}
        if not query:
            params["sort"] = "desc"
        return self._get("posts/search", params)

    def search_comments(self, subreddit: str, query: str = "", limit: int = 25,
                        after: str = "", before: str = "") -> List[Dict[str, Any]]:
        """Recherche des commentaires dans un subreddit.

        L'API Arctic Shift n'expose pas de filtre texte sur comments/search :
        on récupère les commentaires récents du subreddit et le filtrage par
        seed se fait en aval si nécessaire."""
        return self._get("comments/search", {
            "subreddit": subreddit,
            "limit": max(1, min(int(limit), 100)),
            "sort": "desc",
            "after": after,
            "before": before,
        })

    def get_comments_for_post(self, permalink: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Récupère les commentaires d'un thread via son permalink."""
        permalink = (permalink or "").strip("/")
        if not permalink:
            return []
        return self._get("comments/search", {"link_id": permalink, "limit": max(1, min(int(limit), 100)), "sort": "desc"}) or \
            self._get("comments", {"permalink": permalink, "limit": max(1, min(int(limit), 100))})
