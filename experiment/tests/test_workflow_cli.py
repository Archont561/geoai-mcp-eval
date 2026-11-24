"""Tests for experiment workflow CLI commands and Tasknest manifest autodiscovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experiment.adapters import ollama as ollama_adapter
from experiment.adapters import subprocess_runner
from experiment.cli import app
from experiment.services import workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def test_tasknest_autodiscovers_experiment_tasks_from_manifest() -> None:
    from tasknest.discovery import discover_tasks
    from tasknest.validation import validate_registry

    tools_dir = REPO_ROOT / "tools"
    assert not list(tools_dir.glob("experiment_*.py"))
    assert not (tools_dir / "_experiment_common.py").exists()

    registry = discover_tasks(REPO_ROOT)
    validate_registry(registry)

    expected = {
        "experiment.preflight",
        "experiment.model",
        "experiment.run",
        "experiment.harvest",
        "experiment.summary",
        "experiment.prune-ci",
        "experiment.backend-check",
    }
    discovered = {
        name for name, task in registry.tasks.items() if task.package_name == "experiment"
    }
    assert expected.issubset(discovered)
    for name in expected:
        task = registry.tasks[name]
        assert task.is_manifest is True
        assert task.source_path == REPO_ROOT / "experiment" / "pyproject.toml"


def test_workflow_preflight_writes_env_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pixi.lock").write_text("lock-bytes", encoding="utf-8")
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    calls: list[list[str]] = []

    def fake_passthrough(cmd: list[str], **_kwargs: Any) -> int:
        calls.append(list(cmd))
        return 0

    def fake_version(cmd: list[str], _cwd: Path) -> str:
        calls.append(list(cmd))
        return "v1.0.0"

    monkeypatch.setattr(subprocess_runner, "run_passthrough", fake_passthrough)
    monkeypatch.setattr(subprocess_runner, "soft_version", fake_version)
    res = runner.invoke(app, ["env", "preflight", "--run-id", "rid-1"])
    assert res.exit_code == 0, res.output
    pins = (tmp_path / "results" / "rid-1" / "env-pins.txt").read_text(encoding="utf-8")
    assert "repo_sha=v1.0.0" in pins
    assert "pixi_lock_sha256=" in pins
    assert any("validate" in cmd for cmd in calls)


def test_workflow_model_records_digest_and_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(subprocess_runner, "which", lambda _name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_adapter, "start_ollama", lambda *_a, **_kw: None)
    monkeypatch.setattr(ollama_adapter, "wait_ready", lambda *_a, **_kw: True)
    monkeypatch.setattr(ollama_adapter, "pull_model", lambda *_a, **_kw: 0)
    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: "abcdef123456")
    monkeypatch.setattr(
        ollama_adapter,
        "smoke_generate",
        lambda _model, **_kw: {"response": "OK"},
    )
    res = runner.invoke(app, ["env", "model", "--model", "qwen2.5:3b", "--run-id", "rid-m"])
    assert res.exit_code == 0, res.output
    run_dir = tmp_path / "results" / "rid-m"
    assert (run_dir / "model-digest.txt").read_text(encoding="utf-8").strip() == (
        "qwen2.5:3b abcdef123456"
    )
    assert json.loads((run_dir / "model-smoke.json").read_text(encoding="utf-8")) == {
        "response": "OK"
    }


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
    assert seen_reqs[0].arm == "A"
    assert seen_reqs[0].driver == "ollama"
    assert seen_reqs[0].model == "qwen2.5:3b"
    assert seen_reqs[0].model_digest == "sha256:abc123"
    cell_p = tmp_path / "results" / "rid-p" / "analysis-de9im-001" / "A" / "rep-1"
    pilot_manifest = json.loads((cell_p / "manifest.json").read_text(encoding="utf-8"))
    assert pilot_manifest["status"] == "ok"
    assert pilot_manifest["oracle_passed"] is True
    assert pilot_manifest["model_digest"] == "sha256:abc123"
    assert (cell_p / "transcript.jsonl").is_file()

    monkeypatch.setattr(subprocess_runner, "run_passthrough", lambda _cmd, **_kw: 0)
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
    cell_s = tmp_path / "results" / "rid-s" / "analysis-de9im-001" / "B" / "rep-1"
    manifest = json.loads((cell_s / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "mock-smoke"
    assert (cell_s / "transcript.jsonl").is_file()


def test_resolve_pilot_digest_pulls_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    digests = iter(["unknown", "sha256:pulled999"])
    pulled: list[str] = []
    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: next(digests))
    monkeypatch.setattr(
        ollama_adapter, "pull_model", lambda _bin, model: (pulled.append(model), 0)[1]
    )
    assert workflow.workflow_pilot.resolve_pilot_digest("/usr/bin/ollama", "qwen2.5:3b") == (
        "sha256:pulled999"
    )
    assert pulled == ["qwen2.5:3b"]

    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: "unknown")
    monkeypatch.setattr(ollama_adapter, "pull_model", lambda *_a, **_kw: 1)
    with pytest.raises(RuntimeError, match="ollama pull qwen2.5:3b failed"):
        workflow.workflow_pilot.resolve_pilot_digest("/usr/bin/ollama", "qwen2.5:3b")


def test_workflow_harvest_and_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    harvest = tmp_path / "harvest"
    cell = harvest / "experiment-A-analysis-de9im-001-rep1"
    cell.mkdir(parents=True)
    (cell / "manifest.json").write_text(
        json.dumps({"arm": "A", "task": "analysis-de9im-001", "rep": 1, "status": "ok"}),
        encoding="utf-8",
    )
    (harvest / "env-pins.txt").write_text("repo_sha=deadbeef\npython=3.13\n", encoding="utf-8")

    # Missing cells fail loudly by default
    fail_res = runner.invoke(
        app,
        [
            "archive",
            "pack",
            "--harvest-dir",
            str(harvest),
            "--repetitions",
            "1",
            "--skip-oracle",
            "--run-id",
            "rid-h",
        ],
    )
    assert fail_res.exit_code != 0

    # With --no-fail-on-missing succeeds, writes summary.json and RunArchive zip
    out_zip = tmp_path / "experiment-run-rid-h.zip"
    ok_res = runner.invoke(
        app,
        [
            "archive",
            "pack",
            "--harvest-dir",
            str(harvest),
            "--output",
            str(out_zip),
            "--repetitions",
            "1",
            "--no-fail-on-missing",
            "--skip-oracle",
            "--run-id",
            "rid-h",
        ],
    )
    assert ok_res.exit_code == 0, ok_res.output
    assert out_zip.is_file()
    summary = json.loads((harvest / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False
    assert "analysis-de9im-001/A/rep-1" in summary["logged_cells"]

    step_summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    sum_res = runner.invoke(
        app,
        ["archive", "summary", "--harvest-dir", str(harvest), "--run-id", "rid-h"],
    )
    assert sum_res.exit_code == 0, sum_res.output
    md = (harvest / "summary.md").read_text(encoding="utf-8")
    assert "rid-h" in md
    assert "deadbeef" in md
    assert "INCOMPLETE" in md
    assert step_summary.read_text(encoding="utf-8") == md

    # archive summary also renders from a packed RunArchive zip
    zip_sum = runner.invoke(app, ["archive", "summary", "--harvest-dir", str(out_zip)])
    assert zip_sum.exit_code == 0, zip_sum.output
    assert "rid-h" in zip_sum.output

    # archive prune-ci safely no-ops locally
    prune_res = runner.invoke(app, ["archive", "prune-ci", "--keep", "experiment-run-rid-h"])
    assert prune_res.exit_code == 0, prune_res.output
    assert json.loads(prune_res.stdout) == {"kept": "experiment-run-rid-h", "deleted": []}


def test_tasknest_manifest_executes_experiment_summary_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tasknest.testing import CliRunner as TasknestRunner

    harvest = tmp_path / "harvest"
    harvest.mkdir()
    (harvest / "env-pins.txt").write_text("repo_sha=abc123\n", encoding="utf-8")
    monkeypatch.setenv("EXPERIMENT_HARVEST_DIR", str(harvest))
    monkeypatch.setenv("RUN_ID", "manifest-e2e")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    res = TasknestRunner(REPO_ROOT).invoke(["run", "experiment", "summary"])
    assert res.exit_code == 0, res.stdout + res.stderr
    assert (harvest / "summary.md").is_file()
    assert "manifest-e2e" in (harvest / "summary.md").read_text(encoding="utf-8")


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

    eval_res = runner.invoke(app, ["score", "eval", str(zip_path)])
    assert eval_res.exit_code == 0, eval_res.output
    assert "analysis-de9im-001" in eval_res.output

    show_res = runner.invoke(app, ["score", "show", str(zip_path)])
    assert show_res.exit_code == 0, show_res.output
    assert "analysis-de9im-001" in show_res.output

    bad = runner.invoke(app, ["run", "mcp", "--task", "analysis-de9im-001", "--enforce", "N9"])
    assert bad.exit_code != 0


def test_prune_ci_uses_numeric_github_run_id_not_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str]] = []

    def fake_prune(keep: str, *, run_id: str = "") -> list[str]:
        captured.append((keep, run_id))
        return ["experiment-preflight-pins"]

    from experiment.services import archive as archive_service

    monkeypatch.setattr(archive_service, "prune_ci_artifacts", fake_prune)
    monkeypatch.setenv("RUN_ID", "45499999-deadbeef")
    monkeypatch.setenv("GITHUB_RUN_ID", "45499999")
    res = runner.invoke(
        app,
        ["archive", "prune-ci", "--keep", "experiment-run-45499999-deadbeef"],
    )
    assert res.exit_code == 0, res.output
    assert captured == [("experiment-run-45499999-deadbeef", "45499999")]


def test_archive_pack_still_writes_zip_and_summary_on_incomplete_harvest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    harvest = tmp_path / "harvest"
    cell = harvest / "experiment-A-analysis-de9im-001-rep1"
    cell.mkdir(parents=True)
    (cell / "manifest.json").write_text(
        json.dumps({"arm": "A", "task": "analysis-de9im-001", "rep": 1, "status": "ok"}),
        encoding="utf-8",
    )
    out_zip = tmp_path / "bundle" / "experiment-run-partial.zip"
    step_summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))

    res = runner.invoke(
        app,
        [
            "archive",
            "pack",
            "--harvest-dir",
            str(harvest),
            "--output",
            str(out_zip),
            "--repetitions",
            "1",
            "--skip-oracle",
            "--run-id",
            "partial",
        ],
    )
    assert res.exit_code != 0
    assert out_zip.is_file()
    assert "INCOMPLETE" in step_summary.read_text(encoding="utf-8")
