"""Unit tests for ``experiment.cli.run``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experiment.adapters import ollama as ollama_adapter
from experiment.adapters import subprocess_runner
from experiment.cli import app
from experiment.services import workflow

REPO_ROOT = Path(__file__).resolve().parents[3]
runner = CliRunner()


def test_workflow_run_executes_pilot_and_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(subprocess_runner, "which", lambda _name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_adapter, "start_ollama", lambda *_a, **_kw: None)
    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: "sha256:abc123")
    monkeypatch.setattr(
        workflow.paths, "tasks_root", lambda _root=None: REPO_ROOT / "experiment" / "tasks"
    )

    seen_reqs: list[Any] = []

    def fake_run_cell(req: Any) -> dict[str, Any]:
        seen_reqs.append(req)
        (req.cell / "score.json").write_text('{"passed": true}', encoding="utf-8")
        return {
            "status": "ok",
            "oracle_passed": True,
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            "wall_s": 1.25,
            "error": None,
        }

    monkeypatch.setattr(workflow.workflow_pilot.runs_service, "run_cell", fake_run_cell)
    pilot_res = runner.invoke(
        app,
        [
            "run",
            "cell",
            "--arm",
            "A",
            "--task-id",
            "analysis-de9im-001",
            "--stage",
            "pilot",
            "--model",
            "qwen2.5:3b",
            "--run-id",
            "rid-p",
        ],
    )
    assert pilot_res.exit_code == 0, pilot_res.output
    assert len(seen_reqs) == 1
    assert seen_reqs[0].model_digest == "sha256:abc123"
    cell_p = tmp_path / "results" / "rid-p" / "cell-A-analysis-de9im-001-r1"
    pilot_manifest = json.loads((cell_p / "manifest.json").read_text(encoding="utf-8"))
    assert pilot_manifest["status"] == "ok"
    assert pilot_manifest["oracle_passed"] is True

    def fail_passthrough(cmd: list[str], **_kw: Any) -> int:
        raise AssertionError(f"smoke probe must not spawn CLI subprocess: {cmd}")

    monkeypatch.setattr(subprocess_runner, "run_passthrough", fail_passthrough)
    smoke_res = runner.invoke(
        app,
        [
            "run",
            "cell",
            "--arm",
            "B",
            "--task-id",
            "analysis-de9im-001",
            "--stage",
            "smoke",
            "--run-id",
            "rid-s",
        ],
    )
    assert smoke_res.exit_code == 0, smoke_res.output
    cell_s = tmp_path / "results" / "rid-s" / "cell-B-analysis-de9im-001-r1"
    assert json.loads((cell_s / "manifest.json").read_text(encoding="utf-8"))["status"] == (
        "mock-smoke"
    )


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
    assert json.loads(show_res.stdout)["total"] == 2

    zip_path = out_dir.parent / f"experiment-run-{out_dir.name}.zip"
    inspect_res = runner.invoke(app, ["archive", "inspect", str(zip_path), "--json"])
    assert inspect_res.exit_code == 0, inspect_res.output
    inspect_payload = json.loads(inspect_res.stdout)
    assert inspect_payload["trial_count"] == 2
    assert {t["repetition"] for t in inspect_payload["trials"]} == {1, 2}


def test_non_positive_repetitions_and_env_var_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    res = runner.invoke(
        app,
        ["run", "mcp", "--repetitions", "0", "--output-dir", str(tmp_path / "out")],
    )
    assert res.exit_code != 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", res.output)
    assert "--repetitions must be a positive integer" in plain

    captured: list[workflow.WorkflowCellSpec] = []
    monkeypatch.setattr(
        workflow,
        "run_workflow_cell",
        lambda spec: (captured.append(spec), tmp_path / "cell")[1],
    )
    res_new = runner.invoke(
        app,
        ["run", "cell", "--task-id", "analysis-de9im-001", "--cache"],
        env={
            "EXPERIMENT_RUN_ID": "new-run-id",
            "RUN_ID": "legacy-run-id",
            "EXPERIMENT_MODEL": "new-model:7b",
            "MODEL": "legacy-model:3b",
        },
    )
    assert res_new.exit_code == 0, res_new.output
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


def test_run_mcp_enforce_pack_zip_and_score_archive(tmp_path: Path) -> None:
    out_dir = tmp_path / "mcp-n2"
    res = runner.invoke(
        app,
        [
            "run",
            "mcp",
            "--task",
            "analysis-de9im-001",
            "--enforce",
            "N2",
            "--pack-zip",
            "--output-dir",
            str(out_dir),
        ],
    )
    assert res.exit_code == 0, res.output
    zip_path = out_dir.parent / f"experiment-run-{out_dir.name}.zip"
    assert zip_path.is_file()

    insp = runner.invoke(app, ["archive", "inspect", str(zip_path)])
    assert insp.exit_code == 0, insp.output
    assert "syntactic" in insp.output

    from experiment.adapters.run_archive import RunArchive

    with RunArchive.open(zip_path) as arc:
        assert "analysis-de9im-001/typed_mcp/syntactic/rep-1" in arc.run.trials

    bad = runner.invoke(app, ["run", "mcp", "--task", "analysis-de9im-001", "--enforce", "N9"])
    assert bad.exit_code != 0
