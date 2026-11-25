"""Unit tests for ``experiment.services.runs``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from experiment.adapters import _ollama_chat, backends, harness_io, task_repository
from experiment.adapters.llm_cache import CompletionCache
from experiment.services import runs
from experiment.services.runners.ports import CellRequest

TASK_ROOT = harness_io.TASK_ROOT


def _task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == task_id:
            return path
    raise AssertionError(task_id)


def test_cell_error_marks_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("driver exploded")

    monkeypatch.setitem(runs._DRIVER_DISPATCH, ("scripted", "A"), boom)
    cell = tmp_path / "cell"
    cell.mkdir()
    task_path = _task_path("analysis-de9im-001")
    req = CellRequest(
        task_path=task_path,
        task=task_repository.load_task(task_path),
        arm="A",
        driver="scripted",
        cell=cell,
        model="fake",
        host="http://x",
        run_id="test",
    )
    result = runs.run_cell(req)
    assert result["status"] == "error"
    assert result["oracle_passed"] is False


def test_cell_cache_hit_miss_digest_change_and_no_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_path = _task_path("analysis-de9im-001")
    task = task_repository.load_task(task_path)
    cache_dir = tmp_path / "llm-cache"
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    calls = {"n": 0}

    def fake_chat(*_args, **_kwargs) -> dict:
        calls["n"] += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        }

    monkeypatch.setattr(_ollama_chat, "chat_completions_sdk", fake_chat)
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")

    def run_once(name: str, *, digest: str | None, use_cache: bool) -> dict:
        cell = tmp_path / name
        cell.mkdir()
        req = runs.CellRequest(
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
        return runs.run_cell(req)

    first = run_once("c1", digest="sha256:digest-v1", use_cache=True)
    assert first["cache_hit"] is False
    assert first["cache_hits"] == 0
    assert first["cache_misses"] == 1
    assert calls["n"] == 1

    second = run_once("c2", digest="sha256:digest-v1", use_cache=True)
    assert second["cache_hit"] is True
    assert second["cache_hits"] == 1
    assert second["cache_misses"] == 0
    assert calls["n"] == 1

    third = run_once("c3", digest="sha256:digest-v2", use_cache=True)
    assert third["cache_hit"] is False
    assert calls["n"] == 2

    fourth = run_once("c4", digest="sha256:digest-v1", use_cache=False)
    assert fourth["cache_hit"] is False
    assert calls["n"] == 3

    fifth = run_once("c5", digest=None, use_cache=True)
    sixth = run_once("c6", digest=None, use_cache=True)
    assert fifth["cache_hit"] is False
    assert sixth["cache_hit"] is False
    assert calls["n"] == 5


def test_http_errors_are_never_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task_path = _task_path("analysis-de9im-001")
    task = task_repository.load_task(task_path)
    cache_dir = tmp_path / "llm-cache"

    def fail_chat(*_args, **_kwargs) -> dict:
        raise backends.BackendError("http-500", "server error")

    monkeypatch.setattr(_ollama_chat, "chat_completions_sdk", fail_chat)
    cell = tmp_path / "err"
    cell.mkdir()
    req = runs.CellRequest(
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
    res = runs.run_cell(req)
    assert res["status"] == "error"
    assert res["cache_hit"] is False
    assert CompletionCache(cache_dir).count() == 0


def test_scripted_run_writes_manifest_and_explicit_null_usage(tmp_path: Path) -> None:
    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="B", task="analysis-de9im-001", backend="local")
    )
    out = tmp_path / "run-scripted"
    out.mkdir()
    summary = runs.run_experiment(TASK_ROOT, spec, out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["totals"]["cells"] == 1
    assert manifest["totals"]["passed"] == 1
    assert manifest["totals"]["usage"]["input_tokens"] is None
    assert manifest["totals"]["usage"]["total_tokens"] is None
    assert summary.usage == manifest["totals"]["usage"]
    transcript_entries = [
        json.loads(line)
        for line in (out / "cell-B-analysis-de9im-001-r1" / "transcript.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert any(entry.get("event") == "usage_summary" for entry in transcript_entries)
