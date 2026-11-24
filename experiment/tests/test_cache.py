"""Tests for GEO-009: digest-keyed LLM completion cache, --no-cache, and analysis isolation."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import requests
import yaml

import experiment.backends as backends
import experiment.drivers as drivers
from experiment import harness, prototype
from experiment.adapters.llm_cache import CompletionCache
from experiment.domain import cache_key

TASK_ROOT = harness.TASK_ROOT


def _task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == task_id:
            return path
    raise AssertionError(task_id)


def test_build_cache_key_requires_model_digest_and_varies_with_all_inputs() -> None:
    from dataclasses import replace

    spec = cache_key.CacheKeySpec(
        backend_id="local",
        model_digest="sha256:aaaa",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        max_tokens=512,
    )
    base = cache_key.build_cache_key(spec)
    assert len(base) == 64
    assert base == cache_key.build_cache_key(replace(spec))
    variations = (
        replace(spec, backend_id="remote-ollama"),
        replace(spec, model_digest="sha256:bbbb"),
        replace(spec, messages=[{"role": "user", "content": "bye"}]),
        replace(spec, tools=[{"type": "function", "function": {"name": "x"}}]),
        replace(spec, temperature=0.5),
        replace(spec, max_tokens=1024),
    )
    for varied in variations:
        assert base != cache_key.build_cache_key(varied)
    with pytest.raises(ValueError, match="model_digest"):
        cache_key.build_cache_key(replace(spec, model_digest="   "))


def test_completion_cache_persists_successes_and_rejects_error_payloads(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".cache" / "llm"
    cache = CompletionCache(cache_dir)
    ok_payload = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    assert cache.get("k1") is None
    assert cache.put("k1", ok_payload) is True

    # Re-open from disk to prove persistence
    reopened = CompletionCache(cache_dir)
    assert reopened.get("k1") == ok_payload

    # Error payloads are NEVER cached
    assert cache.put("k_err", {"error": {"message": "boom"}}) is False
    assert cache.put("k_empty", {"choices": []}) is False
    assert cache.put("k_bad", {"choices": [{"not_message": 1}]}) is False
    assert reopened.get("k_err") is None
    assert reopened.get("k_empty") is None
    assert reopened.get("k_bad") is None


def test_cell_cache_hit_miss_digest_change_and_no_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_path = _task_path("analysis-de9im-001")
    task = prototype.load_task(task_path)
    cache_dir = tmp_path / "llm-cache"
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    calls = {"n": 0}

    def fake_chat(*_args, **_kwargs) -> dict:
        calls["n"] += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        }

    monkeypatch.setattr(drivers, "_chat_completions", fake_chat)
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")

    def run_once(name: str, *, digest: str | None, use_cache: bool) -> dict:
        cell = tmp_path / name
        cell.mkdir()
        req = prototype.CellRequest(
            task_path=task_path,
            task=task,
            arm="B",
            driver="ollama",
            cell=cell,
            model=profile.model,
            host=str(profile.base_url),
            run_id=name,
            profile=profile,
            backend_id="local",
            model_digest=digest,
            use_cache=use_cache,
            cache_dir=cache_dir,
        )
        return prototype.run_cell(req)

    # 1. Cold miss -> calls endpoint once, populates cache
    first = run_once("c1", digest="sha256:digest-v1", use_cache=True)
    assert first["cache_hit"] is False
    assert first["cache_hits"] == 0
    assert first["cache_misses"] == 1
    assert calls["n"] == 1

    # 2. Warm hit -> same digest, does NOT call endpoint
    second = run_once("c2", digest="sha256:digest-v1", use_cache=True)
    assert second["cache_hit"] is True
    assert second["cache_hits"] == 1
    assert second["cache_misses"] == 0
    assert calls["n"] == 1

    # 3. Digest changed (same model tag!) -> cache miss
    third = run_once("c3", digest="sha256:digest-v2", use_cache=True)
    assert third["cache_hit"] is False
    assert calls["n"] == 2

    # 4. --no-cache -> bypasses cache even for known digest
    fourth = run_once("c4", digest="sha256:digest-v1", use_cache=False)
    assert fourth["cache_hit"] is False
    assert calls["n"] == 3

    # 5. Missing model digest -> never caches under bare tag
    fifth = run_once("c5", digest=None, use_cache=True)
    sixth = run_once("c6", digest=None, use_cache=True)
    assert fifth["cache_hit"] is False
    assert sixth["cache_hit"] is False
    assert calls["n"] == 5


def test_http_errors_are_never_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task_path = _task_path("analysis-de9im-001")
    task = prototype.load_task(task_path)
    cache_dir = tmp_path / "llm-cache"

    def fail_chat(*_args, **_kwargs) -> dict:
        raise backends.BackendError("http-500", "server error")

    monkeypatch.setattr(drivers, "_chat_completions", fail_chat)
    cell = tmp_path / "err"
    cell.mkdir()
    req = prototype.CellRequest(
        task_path=task_path,
        task=task,
        arm="B",
        driver="ollama",
        cell=cell,
        model="qwen2.5:3b",
        host="http://127.0.0.1:11434/v1",
        run_id="err",
        backend_id="local",
        model_digest="sha256:digest-v1",
        use_cache=True,
        cache_dir=cache_dir,
    )
    res = prototype.run_cell(req)
    assert res["status"] == "error"
    assert res["cache_hit"] is False
    assert CompletionCache(cache_dir).count() == 0


def test_analysis_path_contains_no_cache_reads_or_imports() -> None:
    repo = Path(__file__).resolve().parents[2]
    for rel in (
        "experiment/src/experiment/analyze.py",
        "experiment/src/experiment/cli/analyze.py",
    ):
        tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "cache" not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "cache" not in node.module


def test_resolve_model_digest_matches_exact_and_latest_and_handles_failures() -> None:
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")

    class FakeResp:
        def __init__(self, status: int, data: object | None = None, bad_json: bool = False) -> None:
            self.status_code = status
            self._data = data
            self._bad_json = bad_json

        def json(self) -> object:
            if self._bad_json:
                raise ValueError("not json")
            return self._data

    class FakeSession:
        def __init__(self, outcome: FakeResp | Exception) -> None:
            self._outcome = outcome

        def get(self, *_a, **_kw) -> FakeResp:
            if isinstance(self._outcome, Exception):
                raise self._outcome
            return self._outcome

    ok = FakeSession(FakeResp(200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:abc123"}]}))
    assert backends.resolve_model_digest(ok, profile) == "sha256:abc123"  # type: ignore[arg-type]

    untagged = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5")
    latest = FakeSession(
        FakeResp(200, {"models": [{"model": "qwen2.5:latest", "digest": "sha256:def456"}]})
    )
    assert backends.resolve_model_digest(latest, untagged) == "sha256:def456"  # type: ignore[arg-type]

    assert backends.resolve_model_digest(FakeSession(FakeResp(500)), profile) is None  # type: ignore[arg-type]
    assert backends.resolve_model_digest(FakeSession(FakeResp(200, bad_json=True)), profile) is None  # type: ignore[arg-type]
    assert (
        backends.resolve_model_digest(
            FakeSession(requests.exceptions.ConnectionError("down")), profile
        )  # type: ignore[arg-type]
        is None
    )


def test_ci_workflow_has_opt_in_llm_cache_with_prefix_restore_keys() -> None:
    repo = Path(__file__).resolve().parents[2]
    wf = yaml.safe_load((repo / ".github/workflows/experiment.yml").read_text(encoding="utf-8"))
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert inputs["use-llm-cache"]["type"] == "boolean"
    assert inputs["use-llm-cache"]["default"] is False
    steps = wf["jobs"]["run"]["steps"]
    cache_steps = [s for s in steps if s.get("with", {}).get("path") == ".cache/llm"]
    assert len(cache_steps) == 1
    step = cache_steps[0]
    assert "actions/cache@" in step["uses"]
    assert "llm-cache-" in step["with"]["restore-keys"]
