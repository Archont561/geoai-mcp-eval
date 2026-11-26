"""Unit tests for ``experiment.adapters.llm_cache``."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.adapters.llm_cache import CompletionCache


@given(
    key=st.text(alphabet="0123456789abcdef", min_size=4, max_size=32),
    content=st.text(max_size=80),
    prompt_tokens=st.integers(min_value=0, max_value=10000),
    completion_tokens=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_completion_cache_roundtrips_arbitrary_valid_replies(
    tmp_path: Path, key: str, content: str, prompt_tokens: int, completion_tokens: int
) -> None:
    cache_dir = tmp_path / "prop-cache"
    cache = CompletionCache(cache_dir)
    payload = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    assert cache.put(key, payload) is True
    assert CompletionCache(cache_dir).get(key) == payload


@example(payload={"error": {"message": "boom"}})
@example(payload={"choices": []})
@example(payload={"choices": [{"not_message": 1}]})
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    payload=st.one_of(
        st.dictionaries(st.text(max_size=10), st.integers(), max_size=5).map(
            lambda error: {"error": error}
        ),
        st.just({"choices": []}),
        st.integers().map(lambda value: {"choices": [{"not_message": value}]}),
    )
)
def test_completion_cache_rejects_unsuccessful_replies(tmp_path: Path, payload: dict) -> None:
    cache_dir = tmp_path / "invalid-cache"
    cache = CompletionCache(cache_dir)
    assert cache.get("invalid") is None
    assert cache.put("invalid", payload) is False
    assert CompletionCache(cache_dir).get("invalid") is None
