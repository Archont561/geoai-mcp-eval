"""Hosted-workflow scenario bindings."""

import json
from pathlib import Path

import pytest
from pytest_bdd import given, then, when
from typer.testing import CliRunner

from experiment.adapters import subprocess_runner
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.cli import app
from experiment.services import backend_check, workflow, workflow_summary


@given("a hosted workflow collecting progress and summary reports")
def hosted_workflow_context() -> None:
    """The action creates isolated output files for the hosted run."""


@given("hosted trial artifacts and a final run archive")
def hosted_artifacts_context() -> None:
    """The action supplies a simulated hosted artifact service."""


@when(
    "the workflow prepares, harvests, summarizes, and checks readiness",
    target_fixture="hosted_progress",
)
def hosted_workflow_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    gh_out = tmp_path / "github_output.txt"
    gh_summary = tmp_path / "github_summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(gh_summary))
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(workflow_summary, "find_repo_root", lambda: tmp_path)

    # 1. Preflight emits run_id & pins
    (tmp_path / "pixi.lock").write_text("lock", encoding="utf-8")
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
    return gh_out.read_text(encoding="utf-8"), gh_summary.read_text(encoding="utf-8")


@when("the researcher removes intermediate artifacts", target_fixture="pruned_artifacts")
def prune_hosted_artifacts() -> list[str]:
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
    return deleted


@then("the hosted workflow receives the run details and readiness results")
def hosted_workflow_results(hosted_progress: tuple[str, str]) -> None:
    outputs, summary = hosted_progress
    assert "run_id=rid-gh" in outputs and "status=READY" in outputs
    assert "digest=sha256:pin999" in outputs and "rid-gh" in summary


@then("only the intermediate artifacts are deleted")
def intermediate_artifacts_deleted(pruned_artifacts: list[str]) -> None:
    assert pruned_artifacts == ["experiment-preflight-pins", "experiment-A-analysis-de9im-001-rep1"]
