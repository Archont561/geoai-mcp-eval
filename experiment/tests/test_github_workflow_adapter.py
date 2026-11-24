"""Tests for the GitHub Actions workflow output adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from experiment.adapters import subprocess_runner
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.cli import app
from experiment.services import backend_check, workflow, workflow_summary


def test_resolve_run_id_precedence() -> None:
    env = {"RUN_ID": "env-run", "GITHUB_RUN_ID": "99", "GITHUB_SHA": "abcdef1234567890"}
    adapter = GitHubWorkflowAdapter(env=env)
    assert adapter.resolve_run_id("explicit-run") == "explicit-run"
    assert adapter.resolve_run_id("") == "env-run"

    gh_only = GitHubWorkflowAdapter(env={"GITHUB_RUN_ID": "42", "GITHUB_SHA": "1234567890abcdef"})
    assert gh_only.resolve_run_id("") == "42-12345678"

    gh_no_sha = GitHubWorkflowAdapter(env={"GITHUB_RUN_ID": "42"})
    assert gh_no_sha.resolve_run_id("") == "42-local"

    empty = GitHubWorkflowAdapter(env={})
    assert empty.resolve_run_id("").startswith("local-")
    assert empty.resolve_run_id("", fallback_local=False) == "local"


def test_run_url_and_is_actions() -> None:
    local = GitHubWorkflowAdapter(env={})
    assert local.is_actions is False
    assert local.run_url() == ""

    gh = GitHubWorkflowAdapter(
        env={
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "Archont561/geoai-mcp-eval",
            "GITHUB_RUN_ID": "12345",
        }
    )
    assert gh.is_actions is True
    assert gh.run_url() == "https://github.com/Archont561/geoai-mcp-eval/actions/runs/12345"

    enterprise = GitHubWorkflowAdapter(
        env={
            "GITHUB_SERVER_URL": "https://ghe.example.org/",
            "GITHUB_REPOSITORY": "org/repo",
            "GITHUB_RUN_ID": "7",
        }
    )
    assert enterprise.run_url() == "https://ghe.example.org/org/repo/actions/runs/7"


def test_write_outputs_single_and_multiline_and_noop(tmp_path: Path) -> None:
    noop = GitHubWorkflowAdapter(env={})
    assert noop.write_output("run_id", "abc") is False
    assert noop.write_outputs({"a": 1}) is False

    out_file = tmp_path / "gh" / "output.txt"
    adapter = GitHubWorkflowAdapter(env={"GITHUB_OUTPUT": str(out_file)})
    assert adapter.write_outputs({"run_id": "r1", "complete": True}) is True
    assert adapter.write_output("notes", "line1\nEOF\nline2") is True

    text = out_file.read_text(encoding="utf-8")
    assert "run_id=r1\n" in text
    assert "complete=true\n" in text
    assert "notes<<" in text
    assert "line1\nEOF\nline2\n" in text

    with pytest.raises(ValueError, match="output key"):
        adapter.write_output("  ", "val")
    with pytest.raises(ValueError, match="output key"):
        adapter.write_output("bad=key", "val")


def test_write_step_summary_appends_and_noop(tmp_path: Path) -> None:
    assert GitHubWorkflowAdapter(env={}).write_step_summary("# hi") is False

    summary_file = tmp_path / "summary" / "step.md"
    adapter = GitHubWorkflowAdapter(env={"GITHUB_STEP_SUMMARY": str(summary_file)})
    assert adapter.write_step_summary("# First") is True
    assert adapter.write_step_summary("## Second\n") is True
    assert summary_file.read_text(encoding="utf-8") == "# First\n## Second\n"


def test_workflow_commands_emit_github_outputs_via_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh_out = tmp_path / "github_output.txt"
    gh_summary = tmp_path / "github_summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(gh_summary))
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(workflow_summary, "find_repo_root", lambda: tmp_path)

    # 1. Preflight emits run_id & pins
    (tmp_path / "pixi.lock").write_text("lock", encoding="utf-8")
    monkeypatch.setattr(subprocess_runner, "run_passthrough", lambda _cmd, **_kw: 0)
    monkeypatch.setattr(subprocess_runner, "soft_version", lambda _cmd, _cwd: "deadbeef")
    workflow.run_preflight("rid-gh")
    text = gh_out.read_text(encoding="utf-8")
    assert "run_id=rid-gh\n" in text
    assert "repo_sha=deadbeef\n" in text

    # 2. Harvest emits complete & missing_count
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    workflow.run_harvest(
        workflow.HarvestConfig(
            harvest_dir=harvest,
            arms=("A",),
            repetitions=1,
            fail_on_missing=False,
            skip_oracle=True,
            run_id="rid-gh",
        )
    )
    text = gh_out.read_text(encoding="utf-8")
    assert "complete=false\n" in text
    assert "missing_count=3\n" in text

    # 3. Summary writes to GITHUB_STEP_SUMMARY via adapter
    workflow_summary.render_summary(harvest_dir=harvest, run_id="rid-gh")
    assert "rid-gh" in gh_summary.read_text(encoding="utf-8")

    # 4. backend-check CLI emits digest & status to GITHUB_OUTPUT
    monkeypatch.setattr(
        backend_check,
        "run_backend_check",
        lambda _cfg: backend_check.BackendCheckResult(
            status="READY",
            backend="remote-ollama",
            model="qwen2.5:3b",
            digest="sha256:pin999",
            base_url="http://127.0.0.1:11435/v1",
        ),
    )
    res = CliRunner().invoke(app, ["env", "backend-check", "--ssh-host", "gpu-box"])
    assert res.exit_code == 0, res.output
    text = gh_out.read_text(encoding="utf-8")
    assert "status=READY\n" in text
    assert "digest=sha256:pin999\n" in text
    assert json.loads((harvest / "summary.json").read_text(encoding="utf-8"))["run_id"] == "rid-gh"


def test_prune_run_artifacts_deletes_intermediates_and_noops_locally() -> None:
    local_adapter = GitHubWorkflowAdapter(env={})
    assert local_adapter.prune_run_artifacts("experiment-run-1.zip") == []

    class _FakeResp:
        def __init__(self, status_code: int, payload: dict | None = None) -> None:
            self.status_code = status_code
            self._payload = payload or {}

        def json(self) -> dict:
            return self._payload

    class _FakeSession:
        def __init__(self) -> None:
            self.deleted_urls: list[str] = []

        def get(self, _url: str, **_kwargs: object) -> _FakeResp:
            return _FakeResp(
                200,
                {
                    "artifacts": [
                        {"id": 1, "name": "experiment-preflight-pins"},
                        {"id": 2, "name": "experiment-run-42"},
                        {"id": 3, "name": "experiment-A-analysis-de9im-001-rep1"},
                    ]
                },
            )

        def delete(self, url: str, **_kwargs: object) -> _FakeResp:
            self.deleted_urls.append(url)
            return _FakeResp(204)

    session = _FakeSession()
    ci_adapter = GitHubWorkflowAdapter(
        env={
            "GITHUB_REPOSITORY": "Archont561/geoai-mcp-eval",
            "GITHUB_RUN_ID": "42",
            "GITHUB_TOKEN": "tok",
        }
    )
    deleted = ci_adapter.prune_run_artifacts("experiment-run-42", session=session)
    assert deleted == ["experiment-preflight-pins", "experiment-A-analysis-de9im-001-rep1"]
    assert session.deleted_urls == [
        "https://api.github.com/repos/Archont561/geoai-mcp-eval/actions/artifacts/1",
        "https://api.github.com/repos/Archont561/geoai-mcp-eval/actions/artifacts/3",
    ]


def test_write_notice_noops_locally_and_escapes_in_actions() -> None:
    import io

    local = GitHubWorkflowAdapter(env={})
    buf = io.StringIO()
    assert local.write_notice("Title", "hello", stream=buf) is False
    assert buf.getvalue() == ""

    ci = GitHubWorkflowAdapter(env={"GITHUB_ACTIONS": "true"})
    assert ci.write_notice("Run: A,B", "100%\nline2\r", stream=buf) is True
    assert buf.getvalue() == "::notice title=Run%3A A%2CB::100%25%0Aline2%0D\n"
