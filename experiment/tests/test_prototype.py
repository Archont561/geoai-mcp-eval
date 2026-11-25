"""Tests for the prototype cell runner, drivers and scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from experiment.adapters import backends, harness_io, task_repository
from experiment.domain.prompts import extract_json_block
from experiment.domain.task import Task
from experiment.services import runs
from experiment.services.runners.ports import CellRequest

TASK_ROOT = harness_io.TASK_ROOT


def _task_document(**overrides: object) -> Task:
    """A complete, valid task, for helpers that only read one field of it."""
    document = {
        "schema_version": 1,
        "id": "fixture-task",
        "title": "fixture task",
        "prompt": "fixture prompt",
        "family": "A",
        "difficulty_rubric": {
            "tier": 2,
            "n_tools_human": 1,
            "n_steps_human": 1,
            "expressible": "medium",
        },
        "provenance": {
            "source": "constructed",
            "source_url": "https://example.invalid",
            "source_file": "fixture.geojson",
            "source_commit": "0" * 40,
            "license": "CC0",
            "contamination": "constructed",
        },
        "fixtures": {"input": "fixtures/fixture.geojson"},
        "human_baseline": {
            "status": "pending",
            "artifact_dir": "baselines/fixture",
            "produced_with": None,
            "human_time_min": None,
            "human_steps": None,
            "human_tools": [],
        },
        "oracle": {"determinism_runs": 3, "assertions": []},
        "budget_bounds": {"max_tool_calls": 10, "max_wall_s": 60},
        "runs": 2,
        "required_traps": [],
    }
    document.update(overrides)
    return Task.model_validate(document)


def _task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == task_id:
            return path
    raise AssertionError(task_id)


def test_fixture_path_errors(tmp_path: Path) -> None:
    task_path = tmp_path / "t.yaml"
    task = _task_document(fixtures={"input": "missing.geojson"})
    with pytest.raises(ValueError, match="fixture"):
        harness_io.fixture_path(task_path, task)


def test_resolve_output_dir_explicit_and_default(tmp_path: Path) -> None:
    assert harness_io.resolve_output_dir(tmp_path / "out") == tmp_path / "out"
    generated = harness_io.resolve_output_dir(None)
    assert generated.name.startswith("prototype-")
    generated.rmdir()


def test_deliverable_name() -> None:
    for task_path in runs.discover_tasks(TASK_ROOT):
        task = task_repository.load_task(task_path)
        expected = "result.geojson" if task.id == "prep-axis-order-001" else "result.json"
        assert harness_io.deliverable_name(task) == expected


def test_run_python_sandboxed(tmp_path: Path) -> None:
    src = tmp_path / "source.geojson"
    src.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    script = (
        "import json, os\n"
        "data = json.load(open('input.geojson'))\n"
        "open('scratch.tmp', 'w').write('x')\n"
        "out = {'cwd': os.getcwd(), 'files': sorted(os.listdir('.')), 'type': data['type']}\n"
        "print(json.dumps(out))\n"
    )
    completed = harness_io.run_python_sandboxed(script, fixture_src=src)
    assert completed.returncode == 0, completed.stderr
    info = json.loads(completed.stdout)
    assert info["type"] == "FeatureCollection"
    assert info["files"] == ["input.geojson", "scratch.tmp"]
    sandbox_path = Path(info["cwd"])
    assert sandbox_path.name.startswith("geoai-sandbox-")
    assert not sandbox_path.exists()  # temp dir + scratch files cleaned up
    assert src.exists()  # original fixture untouched


def _fixture(task_id: str) -> dict:
    task = task_repository.load_task(_task_path(task_id))
    return json.loads(
        (harness_io.fixture_path(_task_path(task_id), task)).read_text(encoding="utf-8")
    )


FINAL_JSON = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'


def _cell_request(
    task_id: str, arm: str, driver: str, cell: Path, run_id: str = "test"
) -> CellRequest:
    task_path = _task_path(task_id)
    task = task_repository.load_task(task_path)
    return CellRequest(
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

    monkeypatch.setattr(backends, "chat_completions", fake_chat)


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
    result = runs.run_cell(req)
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
    result = runs.run_cell(req)
    assert result["status"] == "ok"  # tool error captured, model still finalized
    assert "no_such_tool" in (cell / "transcript.jsonl").read_text(encoding="utf-8")


def test_ollama_arm_b_executes_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code = (
        "import json, os\n"
        "assert os.listdir('.') == ['input.geojson']\n"
        "fx = json.load(open('input.geojson'))\n"
        "assert fx['type'] == 'FeatureCollection'\n"
        "print(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    )
    _install_fake_chat(monkeypatch, lambda: _content_response(f"```python\n{code}```"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    result = runs.run_cell(req)
    assert result["oracle_passed"] is True
    assert not (cell / "input.geojson").exists()  # staged in temp sandbox, not cell/


def test_ollama_arm_b_bad_code_block_fails_softly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_chat(monkeypatch, lambda: _content_response("no code here, sorry"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    result = runs.run_cell(req)
    assert result["oracle_passed"] is False


def test_cell_error_marks_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("driver exploded")

    monkeypatch.setitem(runs._DRIVER_DISPATCH, ("scripted", "A"), boom)
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "A", "scripted", cell)
    result = runs.run_cell(req)
    assert result["status"] == "error"
    assert result["oracle_passed"] is False


def test_extract_json_block() -> None:
    assert extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_block('junk {"b": 2}') == {"b": 2}
    assert extract_json_block("nothing") is None


def test_ollama_arm_b_ignores_json_fence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A ```json answer must not be executed as Python (regression: fence-tag leak)."""
    answer = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'
    _install_fake_chat(monkeypatch, lambda: _content_response(answer))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    result = runs.run_cell(req)
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
    assert runs.run_cell(req)["oracle_passed"] is True


def test_ollama_arm_b_accepts_untagged_fence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    _install_fake_chat(monkeypatch, lambda: _content_response(f"```\n{code}```"))
    cell = _make_cell(tmp_path)
    req = _cell_request("analysis-de9im-001", "B", "ollama", cell)
    assert runs.run_cell(req)["oracle_passed"] is True
