"""Reconstruction de prompts par in-context learning (ICL).

Approche inspirée de la recherche "prompt recovery from search traces"
(cf. UMass WRA) : au lieu de templates déterministes, on récupère les
couples (fan-outs -> prompt) les plus proches du corpus observé et on les
donne en exemples à un LLM qui génère les candidats.

Pipeline :
    fan-outs cibles
        -> retrieval (embeddings, signature lexicale secondaire)
        -> top-k exemples (prompt, fan-outs) en contexte
        -> LLM génère N prompts candidats
        -> chaque candidat est destiné à être exécuté puis comparé
           aux fan-outs observés (validation par exécution, côté worker)

Fallback : si pas de clé OpenAI ou pas d'exemples, on retombe sur le
reconstructeur déterministe existant (PromptReconstructor).
"""

import json
import math
import warnings
import os
from typing import Iterable, List, Optional

import requests

from analysis.models import PromptCandidate, PromptProvenance
from analysis.reconstruction import PromptReconstructor, ReconstructionExample
from analysis.signatures import build_signature, signature_similarity


LANGUAGE_NAMES = {"fr": "français", "nl": "néerlandais", "en": "anglais"}


class ICLPromptReconstructor(PromptReconstructor):
    def __init__(self, examples: Optional[Iterable[ReconstructionExample]] = None,
                 api_key: str = "", chat_model: str = "gpt-4o-mini",
                 max_context_examples: int = 12, temperature: float = 0.7):
        super().__init__(examples)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.chat_model = chat_model
        self.max_context_examples = max(1, max_context_examples)
        self.temperature = temperature
        self.last_usage = {}
        self.embedding_cache = {}
        self.retrieval_method = "lexical"

    @property
    def icl_available(self) -> bool:
        return bool(self.api_key and self.examples)

    def reconstruct(self, fan_outs: List[str], language: str = "fr", max_candidates: int = 3) -> List[PromptCandidate]:
        ranked = self._rank_examples(fan_outs)
        if not self.icl_available:
            warnings.warn("ICL unavailable or generation failed: explicit deterministic fallback", RuntimeWarning)
            return super().reconstruct(fan_outs, language, max_candidates)

        context = ranked[:self.max_context_examples]
        prompts = self._generate_with_llm(fan_outs, context, language, max_candidates)
        candidates = []
        base_confidence = context[0][0] if context else 0.0
        for text in prompts[:max_candidates]:
            candidates.append(PromptCandidate(
                text=text,
                provenance=PromptProvenance.REVERSE_ENGINEERED,
                source_reference=context[0][1].source_reference if context else "",
                confidence=round(min(0.9, 0.4 + 0.5 * base_confidence), 4),
                expected_fan_outs=list(fan_outs),
                metadata={
                    "method": "icl_retrieval",
                    "language": language,
                    "context_examples": len(context),
                    "top_similarity": round(base_confidence, 4),
                    "model": self.chat_model,
                    "retrieval_method": self.retrieval_method,
                },
            ))
        if not candidates:
            warnings.warn("ICL unavailable or generation failed: explicit deterministic fallback", RuntimeWarning)
            return super().reconstruct(fan_outs, language, max_candidates)
        return candidates

    def _rank_examples(self, fan_outs: List[str]):
        target = build_signature(fan_outs)
        texts = ["\n".join(fan_outs), *["\n".join(e.fan_outs) for e in self.examples]]
        semantic = None
        if self.api_key and self.examples:
            missing = list(dict.fromkeys(t for t in texts if t not in self.embedding_cache))
            try:
                if missing:
                    response = requests.post(
                        "https://api.openai.com/v1/embeddings",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={"model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"), "input": missing},
                        timeout=60,
                    )
                    response.raise_for_status()
                    data = response.json()["data"]
                    if len(data) != len(missing):
                        raise ValueError("Incomplete embeddings response")
                    for row in data:
                        self.embedding_cache[missing[row["index"]]] = row["embedding"]
                vectors = [self.embedding_cache[t] for t in texts]
                def cosine(a, b):
                    if len(a) != len(b) or not a or not any(a) or not any(b):
                        raise ValueError("Invalid embedding vector")
                    return sum(x*y for x,y in zip(a,b)) / math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
                semantic = [cosine(vectors[0], v) for v in vectors[1:]]
                self.retrieval_method = "embeddings_cosine_with_lexical_tiebreak"
            except Exception as error:
                warnings.warn(f"Semantic retrieval unavailable: {type(error).__name__}; lexical fallback", RuntimeWarning)
                self.retrieval_method = "lexical_fallback"
        ranked = []
        for index, example in enumerate(self.examples):
            lexical = signature_similarity(target, build_signature(example.fan_outs))
            score = 0.95 * semantic[index] + 0.05 * lexical if semantic is not None else lexical
            ranked.append((score, example))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    def _generate_with_llm(self, fan_outs: List[str], context, language: str, max_candidates: int) -> List[str]:
        lang_name = LANGUAGE_NAMES.get(language, language)
        shots = []
        for score, example in context:
            fan_out_lines = "\n".join(f"  - {query}" for query in example.fan_outs[:8])
            shots.append(f"Recherches réellement effectuées par le moteur :\n{fan_out_lines}\nPrompt utilisateur original :\n{example.prompt}")
        target_lines = "\n".join(f"  - {query}" for query in fan_outs[:12])
        system = (
            "Tu es un expert en reverse-engineering de prompts destinés aux moteurs "
            "de réponse IA (ChatGPT, Gemini, Perplexity). Quand un utilisateur pose "
            "une question, ces moteurs décomposent en plusieurs requêtes de recherche "
            "web (query fan-out). Ta tâche : à partir des requêtes de recherche "
            "réellement observées, inférer le prompt utilisateur le plus probable.\n\n"
            "Règles :\n"
            "- Les exemples montrent des couples réels (recherches -> prompt).\n"
            "- Le prompt doit être naturel, écrit à la première personne si le style "
            "  des exemples le suggère, et couvrir tous les angles des recherches.\n"
            f"- Écris uniquement en {lang_name}.\n"
            "- Ne mentionne pas les recherches elles-mêmes dans le prompt.\n"
            '- Réponds uniquement en JSON : {"prompts": ["...", "..."]}.'
        )
        user = (
            "Voici des exemples réels :\n\n" + "\n\n---\n\n".join(shots)
            + "\n\n===\n\nRecherches réellement effectuées par le moteur (cible) :\n"
            + target_lines
            + f"\n\nGénère {max_candidates} prompts utilisateur plausibles, du plus au moins probable."
        )
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.chat_model,
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
            self.last_usage = payload.get("usage") or {}
            content = payload["choices"][0]["message"]["content"]
            values = json.loads(content).get("prompts", [])
            return [str(value).strip() for value in values if str(value).strip()]
        except Exception:
            return []
