"""Unit tests for GEO-008 usage accounting and --max-cell-tokens enforcement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from experiment.adapters import backends, harness_io, task_repository
from experiment.adapters.mcp.client import McpToolSession
from experiment.domain import usage as usage_domain
from experiment.services import runs

TASK_ROOT = harness_io.TASK_ROOT


def _task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == task_id:
            return path
    raise AssertionError(task_id)


def test_extract_response_usage_supports_openai_and_input_output_keys() -> None:
    snap = usage_domain.extract_response_usage(
        {"usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100}}
    )
    assert snap.input_tokens == 80
    assert snap.output_tokens == 20
    assert snap.total_tokens == 100
    assert snap.warning is None

    snap_alt = usage_domain.extract_response_usage(
        {"usage": {"input_tokens": 45, "output_tokens": 15}}
    )
    assert snap_alt.input_tokens == 45
    assert snap_alt.output_tokens == 15
    assert snap_alt.total_tokens == 60
    assert snap_alt.warning is None


def test_extract_response_usage_never_estimates_missing_or_invalid_values() -> None:
    missing = usage_domain.extract_response_usage({"choices": []})
    assert missing.input_tokens is None
    assert missing.output_tokens is None
    assert missing.total_tokens is None
    assert missing.warning == "endpoint did not report token usage"

    invalid_bool = usage_domain.extract_response_usage(
        {"usage": {"prompt_tokens": True, "completion_tokens": -5}}
    )
    assert invalid_bool.input_tokens is None
    assert invalid_bool.output_tokens is None
    assert invalid_bool.total_tokens is None
    assert invalid_bool.warning == "endpoint did not report token usage"

    partial = usage_domain.extract_response_usage({"usage": {"prompt_tokens": 50}})
    assert partial.input_tokens == 50
    assert partial.output_tokens is None
    assert partial.total_tokens is None
    assert partial.warning == "endpoint reported partial token usage"


def test_usage_accumulator_sums_multi_turn_calls_and_flags_partial_missing() -> None:
    acc = usage_domain.UsageAccumulator()
    acc.record(usage_domain.UsageSnapshot(100, 30, 130))
    acc.record(usage_domain.UsageSnapshot(150, 45, 195))
    summary = acc.to_summary()
    assert summary["input_tokens"] == 250
    assert summary["output_tokens"] == 75
    assert summary["total_tokens"] == 325
    assert summary["llm_calls"] == 2
    assert summary["calls_with_usage"] == 2
    assert summary["calls_missing_usage"] == 0

    mixed = usage_domain.UsageAccumulator()
    mixed.record(usage_domain.UsageSnapshot(100, 30, 130))
    mixed.record(
        usage_domain.UsageSnapshot(None, None, None, warning="endpoint did not report token usage")
    )
    mixed_summary = mixed.to_summary()
    assert mixed_summary["input_tokens"] is None
    assert mixed_summary["output_tokens"] is None
    assert mixed_summary["total_tokens"] is None
    assert mixed_summary["calls_with_usage"] == 1
    assert mixed_summary["calls_missing_usage"] == 1
    assert "endpoint did not report token usage" in mixed_summary["warnings"]


def test_ollama_arm_a_sums_multiturn_usage_and_aborts_on_token_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_path = _task_path("analysis-de9im-001")
    task = task_repository.load_task(task_path)
    fixture = json.loads(harness_io.fixture_path(task_path, task).read_text(encoding="utf-8"))
    args = json.dumps({"geojson": fixture, "property": "ISO_A3", "equals": "POL"})

    # 1. Under cap: sums across 2 completions
    calls = {"n": 0}

    def responder_ok(*_args, **_kwargs) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "type": "function",
                                    "function": {"name": "feature_info", "arguments": args},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```',
                    }
                }
            ],
            "usage": {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
        }

    monkeypatch.setattr(backends, "chat_completions", responder_ok)
    cell_ok = tmp_path / "ok"
    cell_ok.mkdir()
    req_ok = runs.CellRequest(
        task_path=task_path,
        task=task,
        arm="A",
        driver="ollama",
        cell=cell_ok,
        model="fake",
        host="http://x",
        run_id="r1",
        max_cell_tokens=250,
    )
    res_ok = runs.run_cell(req_ok)
    assert res_ok["status"] == "ok"
    assert res_ok["usage"]["input_tokens"] == 150
    assert res_ok["usage"]["output_tokens"] == 50
    assert res_ok["usage"]["total_tokens"] == 200

    # 2. Cap exceeded on turn 1 -> aborts BEFORE calling MCP tool
    tool_invoked = {"called": False}

    def fail_if_called(*_args, **_kwargs):
        tool_invoked["called"] = True
        raise AssertionError("MCP tool must not execute after token cap is exceeded")

    monkeypatch.setattr(McpToolSession, "call_tool", fail_if_called)
    calls["n"] = 0
    cell_cap = tmp_path / "cap"
    cell_cap.mkdir()
    req_cap = runs.CellRequest(
        task_path=task_path,
        task=task,
        arm="A",
        driver="ollama",
        cell=cell_cap,
        model="fake",
        host="http://x",
        run_id="r2",
        max_cell_tokens=50,
    )
    res_cap = runs.run_cell(req_cap)
    assert res_cap["status"] == "aborted"
    assert res_cap["abort_reason"] == "token_cap_exceeded"
    assert tool_invoked["called"] is False
    assert res_cap["usage"]["total_tokens"] == 80
    assert res_cap["usage"]["cap_exceeded"] is True


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
