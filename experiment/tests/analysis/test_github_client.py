"""Unit tests for ``experiment.analysis.github_client``."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiment.adapters.run_archive import RunArchive
from experiment.adapters.subprocess_runner import CommandResult
from experiment.analysis import GitHubRunClient, GitHubRunError, RunDataset, WorkflowRunSummary
from experiment.services import archive as archive_service
from experiment.services import runs

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_TASKS = REPO_ROOT / "experiment" / "tasks"


def _build_packed_pilot_zip(tmp_path: Path) -> Path:
    out_dir = tmp_path / "pilot-run"
    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="both", task="all", backend="local")
    )
    runs.run_experiment(REAL_TASKS, spec, out_dir)
    zip_path = tmp_path / "experiment-run-pilot-001.zip"
    archive_service.pack_archive(
        archive_service.PackOptions(
            source_dir=out_dir,
            output_zip=zip_path,
            run_id="pilot-001",
            stage="pilot",
            run_harvest=False,
        )
    )
    return zip_path


def test_github_run_client_download_cache_list_latest_and_offline(tmp_path: Path) -> None:
    source_zip = _build_packed_pilot_zip(tmp_path / "src")
    calls: list[list[str]] = []

    def fake_runner(argv: Sequence[str]) -> CommandResult:
        cmd = list(argv)
        calls.append(cmd)
        if cmd[:3] == ["gh", "run", "list"]:
            payload = [
                {
                    "databaseId": 987654321,
                    "headSha": "deadbeef",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "2026-11-24T12:00:00Z",
                    "displayTitle": "Experiment",
                    "url": "https://github.com/org/repo/actions/runs/987654321",
                }
            ]
            return CommandResult(returncode=0, stdout=json.dumps(payload))
        if cmd[:3] == ["gh", "run", "download"]:
            dir_idx = cmd.index("--dir") + 1
            dest = Path(cmd[dir_idx]) / "experiment-run-987654321-deadbeef"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_zip, dest / "experiment-run-987654321-deadbeef.zip")
            return CommandResult(returncode=0)
        return CommandResult(returncode=1, stderr=f"unexpected command: {cmd}")

    client = GitHubRunClient(
        repo="Archont561/geoai-mcp-eval",
        cache_dir=tmp_path / "cache",
        runner=fake_runner,
    )

    runs_list = client.list_runs(limit=5, branch="main")
    assert len(runs_list) == 1
    assert runs_list[0].database_id == 987654321

    with client.load_latest(branch="main") as ds1:
        assert len(ds1.measurements_df()) == 6
    assert sum(1 for c in calls if c[:3] == ["gh", "run", "download"]) == 1

    with client.load_run(987654321) as ds2:
        assert len(ds2.measurements_df()) == 6
    assert sum(1 for c in calls if c[:3] == ["gh", "run", "download"]) == 1

    client.download_run(987654321, cache="refresh")
    assert sum(1 for c in calls if c[:3] == ["gh", "run", "download"]) == 2

    with client.load_zip(source_zip) as offline:
        assert offline.run.run_id == "pilot-001"
        with RunArchive.open(source_zip) as arc:
            wrapped = RunDataset.from_archive(arc)
            assert len(wrapped.measurements_df()) == 6


def test_github_run_client_errors(tmp_path: Path) -> None:
    def failing_runner(_argv: Sequence[str]) -> CommandResult:
        return CommandResult(returncode=1, stderr="auth required")

    client = GitHubRunClient(cache_dir=tmp_path / "cache", runner=failing_runner)
    with pytest.raises(GitHubRunError, match="auth required"):
        client.list_runs()

    def empty_runner(argv: Sequence[str]) -> CommandResult:
        if list(argv)[:3] == ["gh", "run", "list"]:
            return CommandResult(returncode=0, stdout="[]")
        return CommandResult(returncode=0, stdout="")

    empty_client = GitHubRunClient(cache_dir=tmp_path / "cache2", runner=empty_runner)
    with pytest.raises(GitHubRunError, match="no successful completed runs"):
        empty_client.load_latest()
    with pytest.raises(GitHubRunError, match="no experiment-run"):
        empty_client.download_run(111)


def test_github_run_client_default_cache_dir_and_summary_model() -> None:
    from experiment.adapters import paths

    client = GitHubRunClient()
    assert client.cache_dir == paths.find_repo_root() / ".cache" / "gh-runs"

    summary = WorkflowRunSummary(
        database_id=42,
        head_sha="abc",
        status="completed",
        conclusion="success",
        created_at="2026-11-24T12:00:00Z",
        display_title="Run",
        url="https://example.invalid/42",
    )
    assert WorkflowRunSummary.model_validate_json(summary.model_dump_json()) == summary
    with pytest.raises(ValidationError):
        WorkflowRunSummary(**summary.model_dump(), extra=1)  # type: ignore[call-arg]
