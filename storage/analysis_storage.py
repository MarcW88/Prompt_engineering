import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from analysis.models import AnalysisObservation, PromptCandidate, PromptProvenance


class AnalysisStorage:
    def __init__(self, db_path: str = "./output/analysis/observations.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS prompt_candidates (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    source_reference TEXT,
                    confidence REAL NOT NULL,
                    expected_fan_outs TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT,
                    prompt TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    country TEXT NOT NULL,
                    language TEXT NOT NULL,
                    model TEXT,
                    answer TEXT,
                    web_search_triggered INTEGER,
                    raw_response TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES prompt_candidates(id)
                );
                CREATE TABLE IF NOT EXISTS fan_outs (
                    observation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    normalized_query TEXT NOT NULL,
                    PRIMARY KEY(observation_id, position),
                    FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS citations (
                    observation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    text TEXT,
                    PRIMARY KEY(observation_id, position, url),
                    FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS validations (
                    candidate_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    fan_out_reproduction_score REAL NOT NULL,
                    citation_overlap_score REAL NOT NULL,
                    stability_score REAL NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(candidate_id, observation_id),
                    FOREIGN KEY(candidate_id) REFERENCES prompt_candidates(id),
                    FOREIGN KEY(observation_id) REFERENCES observations(id)
                );
                CREATE INDEX IF NOT EXISTS idx_observation_prompt ON observations(prompt);
                CREATE INDEX IF NOT EXISTS idx_observation_provider ON observations(provider, engine);
                CREATE INDEX IF NOT EXISTS idx_fan_out_normalized ON fan_outs(normalized_query);
            """)

    def save_candidate(self, candidate: PromptCandidate):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO prompt_candidates
                (id, text, provenance, source_reference, confidence, expected_fan_outs, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                candidate.id, candidate.text, candidate.provenance.value,
                candidate.source_reference, candidate.confidence,
                json.dumps(candidate.expected_fan_outs, ensure_ascii=False),
                json.dumps(candidate.metadata, ensure_ascii=False),
            ))

    def save_observation(self, observation: AnalysisObservation, candidate_id: Optional[str] = None):
        from analysis.signatures import normalize_query

        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO observations
                (id, candidate_id, prompt, provider, engine, country, language, model, answer,
                 web_search_triggered, raw_response, metadata, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                observation.id, candidate_id, observation.prompt, observation.provider,
                observation.engine, observation.country, observation.language, observation.model,
                observation.answer, observation.web_search_triggered,
                json.dumps(observation.raw_response, ensure_ascii=False),
                json.dumps(observation.metadata, ensure_ascii=False),
                observation.observed_at.isoformat(),
            ))
            conn.execute("DELETE FROM fan_outs WHERE observation_id = ?", (observation.id,))
            conn.execute("DELETE FROM citations WHERE observation_id = ?", (observation.id,))
            conn.executemany(
                "INSERT INTO fan_outs (observation_id, position, query, normalized_query) VALUES (?, ?, ?, ?)",
                [(observation.id, index, query, normalize_query(query)) for index, query in enumerate(observation.fan_outs, 1)]
            )
            conn.executemany(
                "INSERT INTO citations (observation_id, position, url, title, text) VALUES (?, ?, ?, ?, ?)",
                [(observation.id, citation.position or index, citation.url, citation.title, citation.text)
                 for index, citation in enumerate(observation.citations, 1)]
            )

    def save_validation(self, candidate_id: str, observation_id: str, scores: Dict):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO validations
                (candidate_id, observation_id, fan_out_reproduction_score, citation_overlap_score,
                 stability_score, details) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                candidate_id, observation_id,
                scores["fan_out_reproduction_score"], scores["citation_overlap_score"],
                scores["stability_score"], json.dumps(scores, ensure_ascii=False),
            ))

    def list_candidates(self, provenance: Optional[PromptProvenance] = None) -> List[PromptCandidate]:
        query = "SELECT * FROM prompt_candidates"
        params = []
        if provenance:
            query += " WHERE provenance = ?"
            params.append(provenance.value)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [PromptCandidate(
            id=row["id"], text=row["text"], provenance=PromptProvenance(row["provenance"]),
            source_reference=row["source_reference"] or "", confidence=row["confidence"],
            expected_fan_outs=json.loads(row["expected_fan_outs"]), metadata=json.loads(row["metadata"]),
        ) for row in rows]
