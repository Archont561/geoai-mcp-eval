"""Unit tests for ``experiment.adapters.llm_cache``."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters.llm_cache import CompletionCache


@given(
    key=st.text(alphabet="0123456789abcdef", min_size=4, max_size=32),
    content=st.text(max_size=80),
)
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_completion_cache_roundtrips_arbitrary_valid_replies(
    tmp_path: Path, key: str, content: str
) -> None:
    cache_dir = tmp_path / "prop-cache"
    cache = CompletionCache(cache_dir)
    payload = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    assert cache.put(key, payload) is True
    assert CompletionCache(cache_dir).get(key) == payload


def test_completion_cache_persists_successes_and_rejects_error_payloads(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".cache" / "llm"
    cache = CompletionCache(cache_dir)
    ok_payload = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    assert cache.get("k1") is None
    assert cache.put("k1", ok_payload) is True

    reopened = CompletionCache(cache_dir)
    assert reopened.get("k1") == ok_payload

    assert cache.put("k_err", {"error": {"message": "boom"}}) is False
    assert cache.put("k_empty", {"choices": []}) is False
    assert cache.put("k_bad", {"choices": [{"not_message": 1}]}) is False
    assert reopened.get("k_err") is None
    assert reopened.get("k_empty") is None
    assert reopened.get("k_bad") is None
