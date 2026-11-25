"""Tests for GEO-021 Slice 4: canonical cell layout, CLI env/flag alignment, and --json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experiment.adapters import run_store
from experiment.cli import app
from experiment.services import mcp_selftest as mcp_selftest_service
from experiment.services import qgis as qgis_service
from experiment.services import workflow as workflow_service

runner = CliRunner()


def test_canonical_cell_layout_helpers_and_discovery(tmp_path: Path) -> None:
    assert run_store.cell_dir_name("A", "analysis-de9im-001", 2) == "cell-A-analysis-de9im-001-r2"
    assert run_store.parse_cell_dir_name("cell-B-prep-axis-order-001-r3") == (
        "B",
        "prep-axis-order-001",
        3,
    )
    assert run_store.parse_cell_dir_name("not-a-cell") is None
    assert run_store.parse_cell_dir_name("cell-A-task-r0") is None
    with pytest.raises(ValueError, match="repetition"):
        run_store.cell_dir_name("A", "t1", 0)

    c1 = run_store.ensure_dir(run_store.cell_dir_path(tmp_path, "A", "task-1", 1))
    c2 = run_store.ensure_dir(tmp_path / "experiment-B-task-1-rep2")
    run_store.write_json(c2 / "manifest.json", {"arm": "B", "task": "task-1", "rep": 2})

    discovered = run_store.discover_cells(tmp_path)
    assert [(c.arm, c.task_id, c.repetition, c.path) for c in discovered] == [
        ("A", "task-1", 1, c1),
        ("B", "task-1", 2, c2),
    ]
    assert run_store.find_cell_dir(tmp_path, "A", "task-1", 1) == c1
    assert run_store.find_cell_dir(tmp_path, "B", "task-1", 2) == c2


def test_local_repetitions_layout_score_and_archive_json(tmp_path: Path) -> None:
    out_dir = tmp_path / "run-reps"
    res = runner.invoke(
        app,
        [
            "run",
            "mcp",
            "--driver",
            "scripted",
            "--task",
            "analysis-de9im-001",
            "--repetitions",
            "2",
            "--cache",
            "--output-dir",
            str(out_dir),
            "--pack-zip",
        ],
    )
    assert res.exit_code == 0, res.output
    assert (out_dir / "cell-A-analysis-de9im-001-r1" / "score.json").is_file()
    assert (out_dir / "cell-A-analysis-de9im-001-r2" / "score.json").is_file()

    eval_res = runner.invoke(app, ["score", "eval", str(out_dir), "--json"])
    assert eval_res.exit_code == 0, eval_res.output
    eval_payload = json.loads(eval_res.stdout)
    assert eval_payload["total"] == 2
    assert {c["repetition"] for c in eval_payload["cells"]} == {1, 2}

    show_res = runner.invoke(app, ["score", "show", str(out_dir), "--json"])
    assert show_res.exit_code == 0, show_res.output
    show_payload = json.loads(show_res.stdout)
    assert show_payload["total"] == 2

    zip_path = out_dir.parent / f"experiment-run-{out_dir.name}.zip"
    inspect_res = runner.invoke(app, ["archive", "inspect", str(zip_path), "--json"])
    assert inspect_res.exit_code == 0, inspect_res.output
    inspect_payload = json.loads(inspect_res.stdout)
    assert inspect_payload["trial_count"] == 2
    assert {t["repetition"] for t in inspect_payload["trials"]} == {1, 2}


def test_non_positive_repetitions_rejected(tmp_path: Path) -> None:
    res = runner.invoke(
        app,
        ["run", "mcp", "--repetitions", "0", "--output-dir", str(tmp_path / "out")],
    )
    assert res.exit_code != 0
    assert "--repetitions must be a positive integer" in res.output


def test_env_var_precedence_and_cache_flag_alignment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[workflow_service.WorkflowCellSpec] = []

    def fake_run_cell(spec: workflow_service.WorkflowCellSpec) -> Path:
        captured.append(spec)
        return tmp_path / "cell"

    monkeypatch.setattr(workflow_service, "run_workflow_cell", fake_run_cell)

    res = runner.invoke(
        app,
        ["run", "cell", "--task-id", "analysis-de9im-001", "--cache"],
        env={
            "EXPERIMENT_RUN_ID": "new-run-id",
            "RUN_ID": "legacy-run-id",
            "EXPERIMENT_MODEL": "new-model:7b",
            "MODEL": "legacy-model:3b",
        },
    )
    assert res.exit_code == 0, res.output
    assert captured[-1].run_id == "new-run-id"
    assert captured[-1].model == "new-model:7b"
    assert captured[-1].use_cache is True

    res_legacy = runner.invoke(
        app,
        ["run", "cell", "--task-id", "analysis-de9im-001", "--use-cache"],
        env={"RUN_ID": "legacy-run-id", "MODEL": "legacy-model:3b"},
    )
    assert res_legacy.exit_code == 0, res_legacy.output
    assert captured[-1].run_id == "legacy-run-id"
    assert captured[-1].model == "legacy-model:3b"
    assert captured[-1].use_cache is True


def test_inspection_commands_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    show_res = runner.invoke(app, ["tasks", "show", "analysis-de9im-001", "--json"])
    assert show_res.exit_code == 0, show_res.output
    show_data = json.loads(show_res.stdout)
    assert show_data["id"] == "analysis-de9im-001"
    assert isinstance(show_data["assertions"], list)

    val_res = runner.invoke(app, ["tasks", "validate", "--json"])
    assert val_res.exit_code == 0, val_res.output
    val_data = json.loads(val_res.stdout)
    assert val_data["passed"] is True
    assert val_data["task_count"] >= 3

    ops_res = runner.invoke(app, ["env", "mcp-ops", "--json"])
    assert ops_res.exit_code == 0, ops_res.output
    ops_data = json.loads(ops_res.stdout)
    assert any(item["name"] == "relate_de9im" for item in ops_data)

    async def fake_selftest() -> list[tuple[str, str, str]]:
        return [("list_tools", "5 tools", "ok")]

    monkeypatch.setattr(mcp_selftest_service, "selftest_rows", fake_selftest)
    self_res = runner.invoke(app, ["env", "mcp-selftest", "--json"])
    assert self_res.exit_code == 0, self_res.output
    assert json.loads(self_res.stdout) == [
        {"step": "list_tools", "result": "5 tools", "detail": "ok"}
    ]

    monkeypatch.setattr(qgis_service, "qgis_versions", lambda: {"qgis": "4.2.3", "python": "3.13"})
    qgis_ok = runner.invoke(app, ["env", "qgis", "check", "--json"])
    assert qgis_ok.exit_code == 0, qgis_ok.output
    assert json.loads(qgis_ok.stdout) == {
        "available": True,
        "versions": {"qgis": "4.2.3", "python": "3.13"},
    }

    monkeypatch.setattr(qgis_service, "qgis_versions", lambda: None)
    qgis_missing: Any = runner.invoke(app, ["env", "qgis", "check", "--json"])
    assert qgis_missing.exit_code == 3
    assert json.loads(qgis_missing.stdout) == {"available": False, "versions": None}
