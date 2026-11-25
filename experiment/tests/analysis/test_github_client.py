"""Unit tests for ``experiment.analysis.github_client``."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters import paths
from experiment.adapters.run_archive import RunArchive
from experiment.adapters.subprocess_runner import CommandResult
from experiment.analysis import GitHubRunClient, GitHubRunError, RunDataset, WorkflowRunSummary


def test_github_run_client_download_cache_list_latest_and_offline(
    tmp_path: Path,
    packed_pilot_zip: Path,
    fake_subprocess_runner: MagicMock,
) -> None:
    def dispatch(argv: Sequence[str]) -> CommandResult:
        cmd = list(argv)
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
            shutil.copyfile(packed_pilot_zip, dest / "experiment-run-987654321-deadbeef.zip")
            return CommandResult(returncode=0)
        return CommandResult(returncode=1, stderr=f"unexpected command: {cmd}")

    fake_subprocess_runner.side_effect = dispatch
    client = GitHubRunClient(
        repo="Archont561/geoai-mcp-eval",
        cache_dir=tmp_path / "cache",
        runner=fake_subprocess_runner,
    )

    runs_list = client.list_runs(limit=5, branch="main")
    assert len(runs_list) == 1
    assert runs_list[0].database_id == 987654321

    with client.load_latest(branch="main") as ds1:
        assert len(ds1.measurements_df()) == 6
    download_calls = [
        call.args[0]
        for call in fake_subprocess_runner.call_args_list
        if list(call.args[0])[:3] == ["gh", "run", "download"]
    ]
    assert len(download_calls) == 1

    with client.load_run(987654321) as ds2:
        assert len(ds2.measurements_df()) == 6
    download_calls = [
        call.args[0]
        for call in fake_subprocess_runner.call_args_list
        if list(call.args[0])[:3] == ["gh", "run", "download"]
    ]
    assert len(download_calls) == 1

    client.download_run(987654321, cache="refresh")
    download_calls = [
        call.args[0]
        for call in fake_subprocess_runner.call_args_list
        if list(call.args[0])[:3] == ["gh", "run", "download"]
    ]
    assert len(download_calls) == 2

    with client.load_zip(packed_pilot_zip) as offline:
        assert offline.run.run_id == "pilot-001"
        with RunArchive.open(packed_pilot_zip) as arc:
            wrapped = RunDataset.from_archive(arc)
            assert len(wrapped.measurements_df()) == 6


def test_github_run_client_errors(tmp_path: Path, fake_subprocess_runner: MagicMock) -> None:
    fake_subprocess_runner.return_value = CommandResult(returncode=1, stderr="auth required")
    client = GitHubRunClient(cache_dir=tmp_path / "cache", runner=fake_subprocess_runner)
    with pytest.raises(GitHubRunError, match="auth required"):
        client.list_runs()

    fake_subprocess_runner.side_effect = lambda argv: (
        CommandResult(returncode=0, stdout="[]")
        if list(argv)[:3] == ["gh", "run", "list"]
        else CommandResult(returncode=0, stdout="")
    )
    empty_client = GitHubRunClient(cache_dir=tmp_path / "cache2", runner=fake_subprocess_runner)
    with pytest.raises(GitHubRunError, match="no successful completed runs"):
        empty_client.load_latest()
    with pytest.raises(GitHubRunError, match="no experiment-run"):
        empty_client.download_run(111)


@given(
    database_id=st.integers(min_value=1, max_value=10**12),
    head_sha=st.text(alphabet="0123456789abcdef", min_size=7, max_size=40),
    title=st.text(min_size=1, max_size=40),
)
def test_workflow_run_summary_roundtrips_for_arbitrary_runs(
    database_id: int, head_sha: str, title: str
) -> None:
    summary = WorkflowRunSummary(
        database_id=database_id,
        head_sha=head_sha,
        status="completed",
        conclusion="success",
        created_at="2026-11-24T12:00:00Z",
        display_title=title,
        url=f"https://example.invalid/{database_id}",
    )
    assert WorkflowRunSummary.model_validate_json(summary.model_dump_json()) == summary


def test_github_run_client_default_cache_dir_and_extra_field_rejection() -> None:
    client = GitHubRunClient()
    assert client.cache_dir == paths.find_repo_root() / ".cache" / "gh-runs"
    with pytest.raises(ValidationError):
        WorkflowRunSummary(
            database_id=42,
            head_sha="abc",
            status="completed",
            conclusion="success",
            created_at="2026-11-24T12:00:00Z",
            display_title="Run",
            url="https://example.invalid/42",
            extra=1,  # type: ignore[call-arg]
        )
