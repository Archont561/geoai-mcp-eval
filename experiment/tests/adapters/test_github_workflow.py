"""Properties of hosted-workflow outputs and identifiers."""

import io
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.adapters.github_workflow import GitHubWorkflowAdapter

names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)
fixture_settings = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])


@given(explicit=names, env_id=names, run=st.integers(min_value=1), sha=names)
def test_resolve_run_id_precedence(explicit: str, env_id: str, run: int, sha: str) -> None:
    adapter = GitHubWorkflowAdapter(
        env={"RUN_ID": env_id, "GITHUB_RUN_ID": str(run), "GITHUB_SHA": sha}
    )
    assert adapter.resolve_run_id(explicit) == explicit
    assert adapter.resolve_run_id("") == env_id
    gh = GitHubWorkflowAdapter(env={"GITHUB_RUN_ID": str(run), "GITHUB_SHA": sha})
    assert gh.resolve_run_id("") == f"{run}-{sha[:8]}"
    no_sha = GitHubWorkflowAdapter(env={"GITHUB_RUN_ID": str(run)})
    assert no_sha.resolve_run_id("") == f"{run}-local"
    empty = GitHubWorkflowAdapter(env={})
    assert empty.resolve_run_id("").startswith("local-")
    assert empty.resolve_run_id("", fallback_local=False) == "local"


@given(owner=names, repo=names, run=st.integers(min_value=1), enterprise=st.booleans())
def test_run_url_and_is_actions(owner: str, repo: str, run: int, enterprise: bool) -> None:
    local = GitHubWorkflowAdapter(env={})
    assert local.is_actions is False and local.run_url() == ""
    server = "https://ghe.example.org" if enterprise else "https://github.com"
    gh = GitHubWorkflowAdapter(
        env={
            "GITHUB_ACTIONS": "true",
            "GITHUB_SERVER_URL": server + "/",
            "GITHUB_REPOSITORY": f"{owner}/{repo}",
            "GITHUB_RUN_ID": str(run),
        }
    )
    assert gh.is_actions is True
    assert gh.run_url() == f"{server}/{owner}/{repo}/actions/runs/{run}"


@fixture_settings
@example(run_id="r1", notes="line1\nEOF\nline2")
@given(run_id=names, notes=st.text(alphabet="abcEOF\n", min_size=1, max_size=50))
def test_write_outputs_single_and_multiline_and_noop(
    tmp_path: Path, run_id: str, notes: str
) -> None:
    noop = GitHubWorkflowAdapter(env={})
    assert noop.write_output("run_id", run_id) is False
    assert noop.write_outputs({"a": 1}) is False
    out_file = tmp_path / "gh" / "output.txt"
    out_file.unlink(missing_ok=True)
    adapter = GitHubWorkflowAdapter(env={"GITHUB_OUTPUT": str(out_file)})
    assert adapter.write_outputs({"run_id": run_id, "complete": True}) is True
    assert adapter.write_output("notes", notes) is True
    text = out_file.read_text(encoding="utf-8")
    assert f"run_id={run_id}\n" in text and "complete=true\n" in text
    if "\n" in notes:
        assert "notes<<" in text and notes + "\n" in text
    else:
        assert f"notes={notes}\n" in text
    for bad in ("  ", "bad=key"):
        with pytest.raises(ValueError, match="output key"):
            adapter.write_output(bad, "val")


@fixture_settings
@given(first=names, second=names)
def test_write_step_summary_appends_and_noop(tmp_path: Path, first: str, second: str) -> None:
    assert GitHubWorkflowAdapter(env={}).write_step_summary(first) is False
    path = tmp_path / "summary" / "step.md"
    path.unlink(missing_ok=True)
    adapter = GitHubWorkflowAdapter(env={"GITHUB_STEP_SUMMARY": str(path)})
    assert adapter.write_step_summary(first) is True
    assert adapter.write_step_summary(second + "\n") is True
    assert path.read_text(encoding="utf-8") == f"{first}\n{second}\n"


@example(title="Run: A,B", message="100%\nline2\r")
@given(
    title=st.text(alphabet="abc:% ,\n", max_size=30),
    message=st.text(alphabet="abc%\r\n", max_size=30),
)
def test_notice_escapes_control_characters(title: str, message: str) -> None:
    buf = io.StringIO()
    assert not GitHubWorkflowAdapter(env={}).write_notice(title, message, stream=buf)
    assert buf.getvalue() == ""
    ci = GitHubWorkflowAdapter(env={"GITHUB_ACTIONS": "true"})
    assert ci.write_notice(title, message, stream=buf)
    escaped_title = (
        title.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )
    escaped_message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    assert buf.getvalue() == f"::notice title={escaped_title}::{escaped_message}\n"
