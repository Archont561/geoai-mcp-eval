"""Unit tests for ``experiment.services.runs``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from experiment.adapters import _ollama_chat, backends, harness_io
from experiment.adapters.llm_cache import CompletionCache
from experiment.domain.task import Task
from experiment.services import runs
from experiment.services.runners.ports import CellRequest

TASK_ROOT = harness_io.TASK_ROOT


def test_cell_error_marks_status(
    monkeypatch: pytest.MonkeyPatch, sample_cell_request: CellRequest
) -> None:
    boom = MagicMock(side_effect=RuntimeError("driver exploded"))
    monkeypatch.setitem(runs._DRIVER_DISPATCH, ("scripted", "A"), boom)
    req = sample_cell_request.model_copy(update={"driver": "scripted"})
    result = runs.run_cell(req)
    assert result["status"] == "error"
    assert result["oracle_passed"] is False


def test_cell_cache_hit_miss_digest_change_and_no_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    de9im_task_path: Path,
    de9im_task: Task,
) -> None:
    cache_dir = tmp_path / "llm-cache"
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    fake_chat = MagicMock(
        return_value={
            "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        }
    )
    monkeypatch.setattr(_ollama_chat, "chat_completions_sdk", fake_chat)
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")

    base_req = CellRequest(
        task_path=de9im_task_path,
        task=de9im_task,
        arm="B",
        driver="ollama",
        cell=tmp_path / "c1",
        model=profile.model,
        host=str(profile.base_url),
        run_id="c1",
        profile=profile,
        backend_id="local",
        model_digest="sha256:digest-v1",
        use_cache=True,
        cache_dir=cache_dir,
    )

    for name, digest, use_cache, exp_hit, exp_hits, exp_misses, exp_calls in [
        ("c1", "sha256:digest-v1", True, False, 0, 1, 1),
        ("c2", "sha256:digest-v1", True, True, 1, 0, 1),
        ("c3", "sha256:digest-v2", True, False, 0, 1, 2),
        ("c4", "sha256:digest-v1", False, False, 0, 1, 3),
        ("c5", None, True, False, 0, 1, 4),
        ("c6", None, True, False, 0, 1, 5),
    ]:
        cell = tmp_path / name
        cell.mkdir()
        res = runs.run_cell(
            base_req.model_copy(
                update={
                    "cell": cell,
                    "run_id": name,
                    "model_digest": digest,
                    "use_cache": use_cache,
                }
            )
        )
        assert res["cache_hit"] is exp_hit
        assert res["cache_hits"] == exp_hits
        assert res["cache_misses"] == exp_misses
        assert fake_chat.call_count == exp_calls


def test_http_errors_are_never_cached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_cell_request: CellRequest,
) -> None:
    cache_dir = tmp_path / "llm-cache"
    monkeypatch.setattr(
        _ollama_chat,
        "chat_completions_sdk",
        MagicMock(side_effect=backends.BackendError("http-500", "server error")),
    )
    req = sample_cell_request.model_copy(
        update={
            "arm": "B",
            "model": "qwen2.5:3b",
            "host": "http://127.0.0.1:11434/v1",
            "run_id": "err",
            "backend_id": "local",
            "model_digest": "sha256:digest-v1",
            "use_cache": True,
            "cache_dir": cache_dir,
        }
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
