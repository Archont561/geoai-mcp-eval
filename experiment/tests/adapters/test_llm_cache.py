"""Unit tests for ``experiment.adapters.llm_cache``."""

from __future__ import annotations

from pathlib import Path

from experiment.adapters.llm_cache import CompletionCache


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
