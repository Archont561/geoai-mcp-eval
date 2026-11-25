"""Unit tests for ``experiment.cli.archive``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from experiment.cli import app
from experiment.services import archive as archive_service
from experiment.services import workflow

REPO_ROOT = Path(__file__).resolve().parents[3]
runner = CliRunner()


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
    assert "rid-h" in md and "deadbeef" in md and "INCOMPLETE" in md
    assert step_summary.read_text(encoding="utf-8") == md

    zip_sum = runner.invoke(app, ["archive", "summary", "--harvest-dir", str(out_zip)])
    assert zip_sum.exit_code == 0, zip_sum.output
    assert "rid-h" in zip_sum.output

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


def test_prune_ci_uses_numeric_github_run_id_not_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str]] = []

    def fake_prune(keep: str, *, run_id: str = "") -> list[str]:
        captured.append((keep, run_id))
        return ["experiment-preflight-pins"]

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
