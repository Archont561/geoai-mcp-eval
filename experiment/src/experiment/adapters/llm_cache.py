"""``diskcache``-backed on-disk LLM completion cache (``.cache/llm``).

Provenance / cost-reduction cache only — never an interchangeable result store,
and never read by the analysis layer (see ADR 0007). Stores validated success
responses only; error payloads are refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import diskcache

from experiment.domain.cache_key import is_cacheable_response

DEFAULT_CACHE_DIR = Path(".cache/llm")
_DB_FILENAME = "cache.db"


class CompletionCache:
    """Persistent key-value cache backed by ``diskcache.Cache``."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.db_path = self.cache_dir / _DB_FILENAME

    def _open(self) -> diskcache.Cache:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return diskcache.Cache(str(self.cache_dir))

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Return a cached, validated success response or None on miss."""
        if not self.db_path.is_file():
            return None
        with self._open() as cache:
            parsed = cache.get(cache_key)
        return parsed if isinstance(parsed, dict) and is_cacheable_response(parsed) else None

    def put(self, cache_key: str, response: dict[str, Any]) -> bool:
        """Persist a validated success payload; refuse errors and return False."""
        if not is_cacheable_response(response):
            return False
        with self._open() as cache:
            cache.set(cache_key, response)
        return True

    def count(self) -> int:
        """Return the number of cached completions on disk."""
        if not self.db_path.is_file():
            return 0
        with self._open() as cache:
            return len(cache)
