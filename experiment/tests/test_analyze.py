"""Tests for analysis data preparation (flat predicate matrix)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from experiment import analyze
from experiment.cli import _loader

runner = CliRunner()

TASKS = {
    "analysis-de9im-001.yaml": {
        "id": "analysis-de9im-001",
        "oracle": {
            "assertions": [
                {"id": "shared-boundary-relation", "type": "de9im_relation", "predicate": "touches"}
            ]
        },
    },
    "prep-axis-order-001.yaml": {
        "id": "prep-axis-order-001",
        "oracle": {
            "assertions": [
                {
                    "id": "single-output-feature",
                    "type": "geojson_feature_count",
                    "predicate": "feature_count",
                },
                {
                    "id": "representative-point-axis-order",
                    "type": "representative_point_matches",
                    "predicate": "point_axis_order",
                },
            ]
        },
    },
}


def _write_tasks(root: Path) -> Path:
    tasks = root / "tasks"
    tasks.mkdir()
    for name, doc in TASKS.items():
        (tasks / name).write_text(yaml.safe_dump(doc), encoding="utf-8")
    return tasks


def _write_cell(root: Path, task: str, arm: str, checks: list[dict], run_id: str = "r1") -> None:
    cell = root / task / f"arm-{arm}"
    cell.mkdir(parents=True)
    payload = {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "meta": {
            "run_id": run_id,
            "task": task,
            "arm": arm,
            "driver": "ollama",
            "model": "m",
            "status": "ok",
            "error": None,
            "wall_s": 1.0,
            "oracle_passed": all(c["passed"] for c in checks),
            "prototype": True,
        },
    }
    (cell / "score.json").write_text(json.dumps(payload), encoding="utf-8")


def _check(assertion_id: str, passed: bool) -> dict:
    return {"assertion_id": assertion_id, "passed": passed, "message": "m"}


def test_flatten_rows_binary_matrix(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
    results = tmp_path / "results"
    _write_cell(results, "analysis-de9im-001", "B", [_check("shared-boundary-relation", True)])
    _write_cell(
        results,
        "prep-axis-order-001",
        "B",
        [_check("single-output-feature", True), _check("representative-point-axis-order", False)],
        run_id="r2",
    )
    frame = analyze.flatten(results, tasks)
    assert list(frame.columns) == [
        "run_id",
        "task",
        "arm",
        "driver",
        "model",
        "feature_count",
        "point_axis_order",
        "touches",
    ]
    by_task = frame.set_index("task")
    assert by_task.loc["analysis-de9im-001", "touches"] == 1
    assert by_task.loc["prep-axis-order-001", "feature_count"] == 1
    assert by_task.loc["prep-axis-order-001", "point_axis_order"] == 0


def test_missing_check_scores_zero(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
    results = tmp_path / "results"
    _write_cell(results, "prep-axis-order-001", "B", [_check("single-output-feature", True)])
    row = analyze.flatten_rows(results, tasks)[0]
    assert row["point_axis_order"] == 0


def test_unknown_assertion_fails_loudly(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
    results = tmp_path / "results"
    _write_cell(results, "analysis-de9im-001", "B", [_check("mystery-assertion", True)])
    with pytest.raises(ValueError, match="mystery-assertion"):
        analyze.flatten_rows(results, tasks)


def test_load_predicates_roundtrip(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
    assert analyze.load_predicates(tasks) == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
    }


def test_flatten_cli_prints_table(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
    results = tmp_path / "results"
    _write_cell(results, "analysis-de9im-001", "B", [_check("shared-boundary-relation", True)])
    out = runner.invoke(_loader.app, ["analyze", "flatten", str(results), "--tasks", str(tasks)])
    assert out.exit_code == 0
    assert "touches" in out.output
    assert "analysis-de9im-001" in out.output


def test_real_suite_predicates_unique_and_present() -> None:
    repo = Path(__file__).resolve().parents[2]
    mapping = analyze.load_predicates(repo / "experiment" / "tasks")
    assert mapping == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
        "natural-breaks-assignments": "natural_breaks",
    }
