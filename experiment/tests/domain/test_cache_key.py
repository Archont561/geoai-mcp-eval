"""Unit tests for ``experiment.domain.cache_key``."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.cache_key import (
    CacheKeySpec,
    CacheStats,
    build_cache_key,
    is_cacheable_response,
)

NON_EMPTY_TOKEN = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789:-_", min_size=1, max_size=24
)


@given(
    backend_id=NON_EMPTY_TOKEN,
    model_digest=NON_EMPTY_TOKEN,
    temperature=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    max_tokens=st.integers(min_value=1, max_value=16384),
    content=st.text(min_size=0, max_size=80),
)
def test_build_cache_key_is_deterministic_64_hex_chars(
    backend_id: str,
    model_digest: str,
    temperature: float,
    max_tokens: int,
    content: str,
) -> None:
    spec = CacheKeySpec(
        backend_id=backend_id,
        model_digest=model_digest,
        messages=[{"role": "user", "content": content}],
        tools=None,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    digest = build_cache_key(spec)
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)
    assert digest == build_cache_key(spec.model_copy())
    assert digest == build_cache_key(
        spec.model_copy(
            update={"backend_id": f"  {backend_id}  ", "model_digest": f" {model_digest} "}
        )
    )


def test_build_cache_key_requires_model_digest_and_varies_with_all_inputs(
    sample_cache_key_spec: CacheKeySpec,
) -> None:
    base = build_cache_key(sample_cache_key_spec)
    variations = (
        sample_cache_key_spec.model_copy(update={"backend_id": "remote-ollama"}),
        sample_cache_key_spec.model_copy(update={"model_digest": "sha256:bbbb"}),
        sample_cache_key_spec.model_copy(update={"messages": [{"role": "user", "content": "bye"}]}),
        sample_cache_key_spec.model_copy(
            update={"tools": [{"type": "function", "function": {"name": "x"}}]}
        ),
        sample_cache_key_spec.model_copy(update={"temperature": 0.5}),
        sample_cache_key_spec.model_copy(update={"max_tokens": 1024}),
    )
    for varied in variations:
        assert base != build_cache_key(varied)
    with pytest.raises(ValueError, match="model_digest"):
        build_cache_key(sample_cache_key_spec.model_copy(update={"model_digest": "   "}))


@given(events=st.lists(st.booleans(), max_size=25))
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_cache_stats_tracks_hits_and_misses_accurately(events: list[bool]) -> None:
    stats = CacheStats()
    for hit in events:
        stats.record(hit=hit)
    expected_hits = sum(1 for hit in events if hit)
    expected_misses = len(events) - expected_hits
    assert stats.hits == expected_hits
    assert stats.misses == expected_misses
    assert stats.all_hit is (expected_hits > 0 and expected_misses == 0)


def test_cache_key_spec_and_stats_pydantic_validation_and_roundtrip(
    sample_cache_key_spec: CacheKeySpec,
) -> None:
    reloaded = CacheKeySpec.model_validate_json(sample_cache_key_spec.model_dump_json())
    assert reloaded == sample_cache_key_spec
    with pytest.raises(ValidationError):
        CacheKeySpec(**sample_cache_key_spec.model_dump(), extra_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        sample_cache_key_spec.backend_id = "mutated"  # type: ignore[misc]

    stats = CacheStats()
    stats.hits += 2
    assert stats.model_dump() == {"hits": 2, "misses": 0}
    with pytest.raises(ValidationError):
        stats.hits = -1
    assert is_cacheable_response({"choices": [{"message": {"content": "ok"}}]}) is True
    assert is_cacheable_response({"error": "rate_limit"}) is False
