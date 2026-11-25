"""Unit tests for ``experiment.domain.cache_key``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.cache_key import (
    CacheKeySpec,
    CacheStats,
    build_cache_key,
    is_cacheable_response,
)


def _sample_spec() -> CacheKeySpec:
    return CacheKeySpec(
        backend_id="local",
        model_digest="sha256:aaaa",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        max_tokens=512,
    )


def test_build_cache_key_requires_model_digest_and_varies_with_all_inputs() -> None:
    spec = _sample_spec()
    base = build_cache_key(spec)
    assert len(base) == 64
    assert base == build_cache_key(spec.model_copy())
    variations = (
        spec.model_copy(update={"backend_id": "remote-ollama"}),
        spec.model_copy(update={"model_digest": "sha256:bbbb"}),
        spec.model_copy(update={"messages": [{"role": "user", "content": "bye"}]}),
        spec.model_copy(update={"tools": [{"type": "function", "function": {"name": "x"}}]}),
        spec.model_copy(update={"temperature": 0.5}),
        spec.model_copy(update={"max_tokens": 1024}),
    )
    for varied in variations:
        assert base != build_cache_key(varied)
    with pytest.raises(ValueError, match="model_digest"):
        build_cache_key(spec.model_copy(update={"model_digest": "   "}))


def test_cache_key_spec_and_stats_pydantic_validation_and_roundtrip() -> None:
    spec = _sample_spec()
    reloaded = CacheKeySpec.model_validate_json(spec.model_dump_json())
    assert reloaded == spec
    with pytest.raises(ValidationError):
        CacheKeySpec(**spec.model_dump(), extra_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        spec.backend_id = "mutated"  # type: ignore[misc]

    stats = CacheStats()
    stats.hits += 2
    assert stats.model_dump() == {"hits": 2, "misses": 0}
    with pytest.raises(ValidationError):
        stats.hits = -1
    assert is_cacheable_response({"choices": [{"message": {"content": "ok"}}]}) is True
    assert is_cacheable_response({"error": "rate_limit"}) is False
