import json
import math
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Sequence

import requests


@dataclass(frozen=True)
class QuestionRecord:
    signal_id: str
    text: str
    provenance: str
    language: str
    confidence: float
    metadata: Dict


class OpenAIProcessor:
    def __init__(self, api_key: str = "", chat_model: str = "gpt-4o-mini", embedding_model: str = "text-embedding-3-small"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def transform(self, text: str, title: str, language: str) -> List[str]:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=self.headers, json={
            "model": self.chat_model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"Transforme ce contenu utilisateur en 1 à 3 questions naturelles pour un assistant IA. Conserve le besoin, les contraintes et le niveau de précision. N'ajoute aucun sujet absent. Réponds uniquement en JSON avec la clé questions. Langue: {language}."},
                {"role": "user", "content": f"Titre: {title}\n\nContenu: {text}"},
            ],
        }, timeout=90)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        values = json.loads(content).get("questions", [])
        return [str(value).strip() for value in values if str(value).strip()][:3]

    def embeddings(self, texts: Sequence[str], batch_size: int = 100) -> List[List[float]]:
        result = []
        for start in range(0, len(texts), batch_size):
            response = requests.post("https://api.openai.com/v1/embeddings", headers=self.headers, json={"model": self.embedding_model, "input": list(texts[start:start + batch_size])}, timeout=120)
            response.raise_for_status()
            result.extend(item["embedding"] for item in response.json()["data"])
        return result


def signals_to_questions(signals: Iterable[Dict], language: str, transformer: Callable[[str, str, str], List[str]]) -> List[QuestionRecord]:
    questions = []
    seen = set()
    for signal in signals:
        source_type = signal.get("source_type", "")
        text = str(signal.get("raw_text", "")).strip()
        title = str(signal.get("title") or "").strip()
        observed = source_type in {"serp", "gsc_conversation"} or _is_question(title or text)
        values = [title or text] if observed else transformer(text, title, language)
        for value in values:
            normalized = normalize_text(value)
            key = (signal["id"], normalized)
            if not normalized or key in seen:
                continue
            seen.add(key)
            questions.append(QuestionRecord(
                signal_id=signal["id"], text=value.strip(), provenance="observed" if observed else "transformed",
                language=language, confidence=1.0 if observed else 0.7,
                metadata={"platform": signal.get("platform"), "source_type": source_type, "source_url": signal.get("url")},
            ))
    return questions


def normalize_text(text: str) -> str:
    return " ".join(re.findall(r"[\wÀ-ÿ]+", text.casefold()))


def cluster_questions(question_rows: Sequence[Dict], embeddings: Sequence[Sequence[float]], threshold: float = 0.82, min_cluster_size: int = 2) -> List[Dict]:
    if len(question_rows) != len(embeddings):
        raise ValueError("questions and embeddings must have the same length")
    parent = list(range(len(question_rows)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    normalized_embeddings = [_normalize_vector(vector) for vector in embeddings]
    for left in range(len(question_rows)):
        for right in range(left + 1, len(question_rows)):
            if _dot(normalized_embeddings[left], normalized_embeddings[right]) >= threshold:
                union(left, right)
    groups = {}
    for index in range(len(question_rows)):
        groups.setdefault(find(index), []).append(index)
    clusters = []
    for indices in groups.values():
        vectors = [normalized_embeddings[index] for index in indices]
        centroid = _normalize_vector([sum(values) / len(values) for values in zip(*vectors)])
        representative_index = max(indices, key=lambda index: _dot(normalized_embeddings[index], centroid))
        representative = question_rows[representative_index]["text"]
        sources = {question_rows[index].get("metadata", {}).get("platform") for index in indices}
        sources.discard(None)
        clusters.append({
            "label": "_".join(normalize_text(representative).split()[:5]),
            "representative_question": representative,
            "question_count": len(indices),
            "source_count": len(sources),
            "is_geo_relevant": len(indices) >= min_cluster_size,
            "fingerprint": _fingerprint(question_rows, indices),
            "members": [{"question_id": question_rows[index]["id"], "similarity": round(_dot(normalized_embeddings[index], centroid), 4)} for index in indices],
        })
    return sorted(clusters, key=lambda cluster: cluster["question_count"], reverse=True)


def _is_question(text: str) -> bool:
    return text.rstrip().endswith("?") or bool(re.match(r"^(comment|pourquoi|quand|où|qui|quel|quelle|quels|quelles|combien|est-ce|how|why|what|which|where|when)\b", text.casefold()))


def _normalize_vector(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _fingerprint(rows: Sequence[Dict], indices: Sequence[int]) -> str:
    import hashlib
    values = sorted(normalize_text(rows[index]["text"]) for index in indices)
    return hashlib.sha256("|".join(values).encode()).hexdigest()
