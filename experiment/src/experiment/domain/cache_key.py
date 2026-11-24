"""Pure cache key computation and per-cell cache statistics.

Zero I/O and zero framework imports. Keys are SHA-256 hashes over canonical JSON
carrying ``backend_id``, ``model_digest`` (never a bare tag), ``messages``,
``tools``, ``temperature``, and ``max_tokens``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def build_cache_key(
    *,
    backend_id: str,
    model_digest: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None,
    temperature: float,
    max_tokens: int,
) -> str:
    """Compute a deterministic SHA-256 cache key pinned to ``model_digest``."""
    clean_backend = backend_id.strip()
    clean_digest = model_digest.strip()
    if not clean_backend:
        raise ValueError("backend_id must be non-empty")
    if not clean_digest:
        raise ValueError("model_digest must be non-empty (never key on bare tag)")
    payload = {
        "backend_id": clean_backend,
        "model_digest": clean_digest,
        "messages": list(messages),
        "tools": list(tools) if tools else None,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def is_cacheable_response(payload: Any) -> bool:
    """Return True only for valid, non-error chat-completion payloads."""
    if not isinstance(payload, Mapping) or "error" in payload:
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    return isinstance(first, Mapping) and isinstance(first.get("message"), Mapping)


@dataclass
class CacheStats:
    """Counts cache hits and misses across all completions in one cell."""

    hits: int = 0
    misses: int = 0

    def record(self, *, hit: bool) -> None:
        if hit:
            self.hits += 1
        else:
            self.misses += 1

    @property
    def all_hit(self) -> bool:
        return self.hits > 0 and self.misses == 0
