"""Tests for the prototype cell runner, drivers and scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import experiment.drivers as drivers
from experiment import harness, prototype

TASK_ROOT = harness.TASK_ROOT


def _task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == task_id:
            return path
    raise AssertionError(task_id)


def test_discover_tasks_finds_three() -> None:
    assert len(prototype.discover_tasks(TASK_ROOT)) == 3


def test_load_task_rejects_non_task(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        prototype.load_task(bad)


def test_fixture_path_errors(tmp_path: Path) -> None:
    task_path = tmp_path / "t.yaml"
    task_path.write_text(yaml.safe_dump({"id": "x", "fixtures": {"input": "missing.geojson"}}))
    with pytest.raises(ValueError, match="fixture"):
        harness.fixture_path(task_path, {"fixtures": {"input": "missing.geojson"}})


def test_resolve_output_dir_explicit_and_default(tmp_path: Path) -> None:
    assert harness.resolve_output_dir(tmp_path / "out") == tmp_path / "out"
    generated = harness.resolve_output_dir(None)
    assert generated.name.startswith("prototype-")
    generated.rmdir()


def test_deliverable_name() -> None:
    for task_path in prototype.discover_tasks(TASK_ROOT):
        task = prototype.load_task(task_path)
        expected = "result.geojson" if task["id"] == "prep-axis-order-001" else "result.json"
        assert harness.deliverable_name(task) == expected


def test_run_python_sandboxed() -> None:
    completed = harness.run_python_sandboxed("print('hello')", Path("."))
    assert completed.returncode == 0
    assert completed.stdout.strip() == "hello"


def test_score_cell_pass_and_fail(tmp_path: Path) -> None:
    task_path = _task_path("analysis-de9im-001")
    good = tmp_path / "good"
    good.mkdir()
    (good / "result.json").write_text(json.dumps({"relation": "touches", "de9im": "FF2F11212"}))
    verdict = prototype.score_cell(task_path, good)
    assert verdict["passed"] is True  # score.json is written by run_cell, not score_cell
    assert verdict["checks"]
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "result.json").write_text(json.dumps({"relation": "disjoint", "de9im": "FF*FF****"}))
    assert prototype.score_cell(task_path, bad)["passed"] is False


def test_run_experiment_scripted_end_to_end(tmp_path: Path) -> None:
    spec = prototype.RunSpec(
        arms=("A", "B"), task_ids=None, driver="scripted", model="unused", host="http://127.0.0.1:1"
    )
    summary = prototype.run_experiment(TASK_ROOT, spec, tmp_path)
    assert summary["total"] == 6
    assert summary["passed"] == 6
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["cells"][0]["prototype"] is True

    def _transcript_path(cell_meta: dict) -> Path:
        return tmp_path / cell_meta["task"] / f"arm-{cell_meta['arm']}" / "transcript.jsonl"

    assert all(_transcript_path(c).is_file() for c in payload["cells"])


def _fixture(task_id: str) -> dict:
    task = prototype.load_task(_task_path(task_id))
    return json.loads((harness.fixture_path(_task_path(task_id), task)).read_text(encoding="utf-8"))


FINAL_JSON = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'


def _cell_request(
    task_id: str, arm: str, driver: str, cell: Path, run_id: str = "test"
) -> prototype.CellRequest:
    task_path = _task_path(task_id)
    task = prototype.load_task(task_path)
    return prototype.CellRequest(
        task_path=task_path,
        task=task,
        arm=arm,
        driver=driver,
        cell=cell,
        model="fake",
        host="http://x",
        run_id=run_id,
    )


def _make_cell(tmp_path: Path) -> Path:
    cell = tmp_path / "cell"
    cell.mkdir()
    return cell


def _tool_call_response(name: str, arguments: str) -> dict:
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
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                }
            }
        ]
    }


def _content_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _install_fake_chat(monkeypatch: pytest.MonkeyPatch, responder) -> None:
    def fake_chat(*_args, **_kwargs):
        return responder()

    monkeypatch.setattr(drivers, "_chat_completions", fake_chat)


def test_ollama_arm_a_tool_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixture = _fixture("analysis-de9im-001")
    args = json.dumps({"geojson": fixture, "property": "ISO_A3", "equals": "POL"})
    calls = {"n": 0}

    def responder() -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return _tool_call_response("feature_info", args)
        return _content_response(FINAL_JSON)

    _install_fake_chat(monkeypatch, responder)
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "A", "ollama", cell)
    result = prototype.run_cell(req)
    assert result["status"] == "ok"
    assert result["oracle_passed"] is True
    transcript = (cell / "transcript.jsonl").read_text(encoding="utf-8")
    assert "feature_info" in transcript


def test_ollama_arm_a_tool_error_is_captured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"n": 0}

    def responder() -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return _tool_call_response("no_such_tool", "{}")
        return _content_response(FINAL_JSON)

    _install_fake_chat(monkeypatch, responder)
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "A", "ollama", cell)
    result = prototype.run_cell(req)
    assert result["status"] == "ok"  # tool error captured, model still finalized
    assert "no_such_tool" in (cell / "transcript.jsonl").read_text(encoding="utf-8")


def test_ollama_arm_b_executes_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    _install_fake_chat(monkeypatch, lambda: _content_response(f"```python\n{code}```"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    result = prototype.run_cell(req)
    assert result["oracle_passed"] is True


def test_ollama_arm_b_bad_code_block_fails_softly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_chat(monkeypatch, lambda: _content_response("no code here, sorry"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    result = prototype.run_cell(req)
    assert result["oracle_passed"] is False


def test_cell_error_marks_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("driver exploded")

    monkeypatch.setitem(prototype._DRIVER_DISPATCH, ("scripted", "A"), boom)
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "A", "scripted", cell)
    result = prototype.run_cell(req)
    assert result["status"] == "error"
    assert result["oracle_passed"] is False


def test_extract_json_block() -> None:
    assert drivers._extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert drivers._extract_json_block('junk {"b": 2}') == {"b": 2}
    assert drivers._extract_json_block("nothing") is None


def test_ollama_arm_b_ignores_json_fence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A ```json answer must not be executed as Python (regression: fence-tag leak)."""
    answer = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'
    _install_fake_chat(monkeypatch, lambda: _content_response(answer))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    result = prototype.run_cell(req)
    assert result["oracle_passed"] is False
    assert not (cell / "result.json").exists()
    transcript = (cell / "transcript.jsonl").read_text(encoding="utf-8")
    assert "no python block found" in transcript
    assert "<string>" not in transcript  # code was never run


def test_ollama_arm_b_accepts_py_fence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    _install_fake_chat(monkeypatch, lambda: _content_response(f"```py\n{code}```"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    assert prototype.run_cell(req)["oracle_passed"] is True


def test_ollama_arm_b_accepts_untagged_fence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    _install_fake_chat(monkeypatch, lambda: _content_response(f"```\n{code}```"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    assert prototype.run_cell(req)["oracle_passed"] is True
