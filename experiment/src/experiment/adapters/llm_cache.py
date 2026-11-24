"""SQLite-backed on-disk LLM completion cache (`.cache/llm`).

Provenance / cost-reduction cache only — never an interchangeable result store,
and never read by the analysis layer (see ADR 0007). Stores validated success
responses only; error payloads are refused.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment.domain.cache_key import is_cacheable_response

DEFAULT_CACHE_DIR = Path(".cache/llm")
_DB_FILENAME = "completions.sqlite3"


class CompletionCache:
    """Persistent key-value cache stored in SQLite (WAL mode)."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.db_path = self.cache_dir / _DB_FILENAME
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        if not self._initialized:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completions (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            self._initialized = True
        return conn

    def get(self, cache_key: str) -> dict[str, Any] | None:
        if not self.db_path.is_file():
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT response_json FROM completions WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        parsed = json.loads(row[0])
        return parsed if is_cacheable_response(parsed) else None

    def put(self, cache_key: str, response: dict[str, Any]) -> bool:
        """Persist a validated success payload; refuse errors and return False."""
        if not is_cacheable_response(response):
            return False
        serialized = json.dumps(response, sort_keys=True)
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO completions (cache_key, response_json, created_at)
                VALUES (?, ?, ?)
                """,
                (cache_key, serialized, now),
            )
            conn.commit()
        return True

    def count(self) -> int:
        if not self.db_path.is_file():
            return 0
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM completions").fetchone()
        return int(row[0]) if row else 0
