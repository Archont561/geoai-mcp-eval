"""Pure cache key computation and per-trial cache statistics.

Zero I/O and zero framework imports. Keys are SHA-256 hashes over canonical JSON
carrying ``backend_id``, ``model_digest`` (never a bare tag), ``messages``,
``tools``, ``temperature``, and ``max_tokens``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CacheKeySpec(BaseModel):
    """All inputs that determine a deterministic LLM completion cache key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend_id: str
    model_digest: str
    messages: Sequence[Mapping[str, Any]]
    tools: Sequence[Mapping[str, Any]] | None = None
    temperature: float
    max_tokens: int


def build_cache_key(spec: CacheKeySpec) -> str:
    """Compute a deterministic SHA-256 cache key pinned to ``spec.model_digest``."""
    clean_backend = spec.backend_id.strip()
    clean_digest = spec.model_digest.strip()
    if not clean_backend:
        raise ValueError("backend_id must be non-empty")
    if not clean_digest:
        raise ValueError("model_digest must be non-empty (never key on bare tag)")
    payload = {
        "backend_id": clean_backend,
        "model_digest": clean_digest,
        "messages": list(spec.messages),
        "tools": list(spec.tools) if spec.tools else None,
        "temperature": float(spec.temperature),
        "max_tokens": int(spec.max_tokens),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _is_mapping(obj: Any) -> bool:
    return isinstance(obj, Mapping)


def _has_choice_message(choices: Any) -> bool:
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    return _is_mapping(first) and _is_mapping(first.get("message"))


def is_cacheable_response(payload: Any) -> bool:
    """Return True only for valid, non-error chat-completion payloads."""
    if not _is_mapping(payload) or "error" in payload:
        return False
    return _has_choice_message(payload.get("choices"))


class CacheStats(BaseModel):
    """Counts cache hits and misses across all completions in one trial."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    hits: int = Field(default=0, ge=0)
    misses: int = Field(default=0, ge=0)

    def record(self, *, hit: bool) -> None:
        if hit:
            self.hits += 1
        else:
            self.misses += 1

    @property
    def all_hit(self) -> bool:
        return self.hits > 0 and self.misses == 0
