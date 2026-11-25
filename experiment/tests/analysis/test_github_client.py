"""Unit and property tests for ``experiment.analysis.github_client`` (``PyGithub`` + ``httpx``)."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from github import GithubException
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters import paths
from experiment.adapters.run_archive import RunArchive
from experiment.analysis import (
    CachePolicy,
    GitHubRunClient,
    GitHubRunError,
    GitHubTransport,
    RunDataset,
    WorkflowRunSummary,
)


def _wrap_in_outer_artifact_zip(inner_zip: Path, member_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, inner_zip.read_bytes())
    return buf.getvalue()


@pytest.fixture
def fake_pygithub(packed_pilot_zip: Path) -> tuple[MagicMock, MagicMock]:
    """Return ``(github_client, http_client)`` mocks simulating PyGithub + 302 artifact redirect."""
    run = MagicMock(name="workflow_run")
    run.id = 987654321
    run.head_sha = "deadbeef"
    run.status = "completed"
    run.conclusion = "success"
    run.created_at = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    run.display_title = "Experiment"
    run.html_url = "https://github.com/org/repo/actions/runs/987654321"

    artifact = MagicMock(name="artifact")
    artifact.name = "experiment-run-987654321-deadbeef"
    artifact.expired = False
    artifact.archive_download_url = (
        "https://api.github.com/repos/Archont561/geoai-mcp-eval/actions/artifacts/555/zip"
    )
    run.get_artifacts.return_value = [artifact]

    workflow = MagicMock(name="workflow")
    workflow.get_runs.return_value = [run]

    repo = MagicMock(name="repo")
    repo.get_workflow.return_value = workflow
    repo.get_workflow_run.return_value = run

    gh = MagicMock(name="github_client")
    gh.get_repo.return_value = repo

    outer_bytes = _wrap_in_outer_artifact_zip(
        packed_pilot_zip, "experiment-run-987654321-deadbeef.zip"
    )
    redirect_resp = MagicMock(spec=httpx.Response)
    redirect_resp.status_code = 302
    redirect_resp.headers = {"location": "https://blob.example.invalid/sas-artifact.zip"}
    redirect_resp.content = b""

    blob_resp = MagicMock(spec=httpx.Response)
    blob_resp.status_code = 200
    blob_resp.headers = {}
    blob_resp.content = outer_bytes

    def http_get(url: str, **_kwargs: Any) -> MagicMock:
        if "api.github.com" in url:
            return redirect_resp
        return blob_resp

    http_client = MagicMock(spec=httpx.Client)
    http_client.get.side_effect = http_get
    return gh, http_client


def test_github_run_client_download_redirect_cache_corruption_and_offline(
    tmp_path: Path,
    packed_pilot_zip: Path,
    fake_pygithub: tuple[MagicMock, MagicMock],
) -> None:
    gh, http_client = fake_pygithub
    client = GitHubRunClient(
        repo="Archont561/geoai-mcp-eval",
        token="ghp_test_secret",
        cache_dir=tmp_path / "cache",
        transport=GitHubTransport(github_client=gh, http_client=http_client),
    )

    runs_list = client.list_runs(limit=5, branch="main")
    assert len(runs_list) == 1
    assert runs_list[0].database_id == 987654321
    assert runs_list[0].head_sha == "deadbeef"

    # First load downloads via 302 redirect and strips Authorization on the blob host.
    with client.load_latest(branch="main") as ds1:
        assert len(ds1.measurements_df()) == 6
    assert http_client.get.call_count == 2
    first_call_headers = http_client.get.call_args_list[0].kwargs["headers"]
    second_call_kwargs = http_client.get.call_args_list[1].kwargs
    assert first_call_headers["Authorization"] == "Bearer ghp_test_secret"
    assert "headers" not in second_call_kwargs

    # Second load hits local cache without any HTTP call.
    with client.load_run(987654321) as ds2:
        assert len(ds2.measurements_df()) == 6
    assert http_client.get.call_count == 2

    # Explicit refresh forces re-download.
    cached_path = client.download_run(987654321, cache=CachePolicy.REFRESH)
    assert http_client.get.call_count == 4

    # Corrupting the cached zip triggers automatic re-download on CachePolicy.USE.
    cached_path.write_bytes(b"corrupted-not-a-zip")
    recovered = client.download_run(987654321, cache=CachePolicy.USE)
    assert recovered.is_file()
    assert http_client.get.call_count == 6

    # Offline loading works without network or PyGithub.
    with client.load_zip(packed_pilot_zip) as offline:
        assert offline.run.run_id == "pilot-001"
        with RunArchive.open(packed_pilot_zip) as arc:
            wrapped = RunDataset.from_archive(arc)
            assert len(wrapped.measurements_df()) == 6


def test_github_run_client_direct_zip_and_env_token_resolution(
    tmp_path: Path,
    packed_pilot_zip: Path,
    fake_pygithub: tuple[MagicMock, MagicMock],
) -> None:
    gh, http_client = fake_pygithub
    direct_resp = MagicMock(spec=httpx.Response)
    direct_resp.status_code = 200
    direct_resp.headers = {}
    direct_resp.content = packed_pilot_zip.read_bytes()
    http_client.get.side_effect = None
    http_client.get.return_value = direct_resp

    client = GitHubRunClient(
        cache_dir=tmp_path / "cache",
        transport=GitHubTransport(
            github_client=gh,
            http_client=http_client,
            env={"GH_TOKEN": "gho_env_token", "GITHUB_REPOSITORY": "Archont561/geoai-mcp-eval"},
        ),
    )
    zip_path = client.download_run(987654321)
    assert zip_path.name == "experiment-run-987654321-deadbeef.zip"
    assert http_client.get.call_args.kwargs["headers"]["Authorization"] == "Bearer gho_env_token"


def test_github_run_client_errors(
    tmp_path: Path,
    fake_pygithub: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh, http_client = fake_pygithub
    gh.get_repo.side_effect = GithubException(401, {"message": "Bad credentials"}, None)
    client = GitHubRunClient(
        repo="org/repo",
        cache_dir=tmp_path / "c1",
        transport=GitHubTransport(github_client=gh, http_client=http_client),
    )
    with pytest.raises(GitHubRunError, match="GitHub API error"):
        client.list_runs()

    # Empty runs and missing matching artifact.
    gh.get_repo.side_effect = None
    repo = gh.get_repo.return_value
    repo.get_workflow.return_value.get_runs.return_value = []
    repo.get_workflow_run.return_value.get_artifacts.return_value = []
    with pytest.raises(GitHubRunError, match="no successful completed runs"):
        client.load_latest()
    with pytest.raises(GitHubRunError, match="no experiment-run"):
        client.download_run(111)

    # HTTP transport error and invalid zip payload.
    art = MagicMock(name="art")
    art.name = "experiment-run-111"
    art.expired = False
    art.archive_download_url = "https://api.github.com/artifacts/111/zip"
    repo.get_workflow_run.return_value.get_artifacts.return_value = [art]

    http_client.get.side_effect = httpx.ConnectError("network down")
    with pytest.raises(GitHubRunError, match="artifact download failed"):
        client.download_run(111)

    bad_resp = MagicMock(spec=httpx.Response)
    bad_resp.status_code = 200
    bad_resp.headers = {}
    bad_resp.content = b"not-a-zip"
    http_client.get.side_effect = None
    http_client.get.return_value = bad_resp
    with pytest.raises(GitHubRunError, match="not a valid zip"):
        client.download_run(111)

    # HTTP 404 from artifact endpoint and redirect missing Location header.
    err_resp = MagicMock(spec=httpx.Response)
    err_resp.status_code = 404
    err_resp.headers = {}
    err_resp.content = b""
    http_client.get.return_value = err_resp
    with pytest.raises(GitHubRunError, match="HTTP 404"):
        client.download_run(111)

    bad_redirect = MagicMock(spec=httpx.Response)
    bad_redirect.status_code = 302
    bad_redirect.headers = {}
    bad_redirect.content = b""
    http_client.get.return_value = bad_redirect
    with pytest.raises(GitHubRunError, match="missing Location"):
        client.download_run(111)

    # Missing repo resolution when env and git config have no GitHub remote.
    no_repo_client = GitHubRunClient(
        cache_dir=tmp_path / "c2",
        transport=GitHubTransport(github_client=gh, http_client=http_client, env={}),
    )
    monkeypatch.setattr(paths, "find_repo_root", lambda: tmp_path)
    with pytest.raises(GitHubRunError, match="repository not configured"):
        no_repo_client.list_runs()

    # Pure-Python .git/config remote parsing resolves owner/repo without gh or git CLI.
    git_dir = tmp_path / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/Archont561/geoai-mcp-eval.git\n',
        encoding="utf-8",
    )
    assert no_repo_client.list_runs() == []


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
