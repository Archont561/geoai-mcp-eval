"""Executable specifications for analysis of archived runs."""

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from fakes import _wrap_in_outer_artifact_zip
from pytest_bdd import given, parsers, scenarios, then, when

from experiment.adapters.run_archive import RunArchive
from experiment.analysis import (
    ASSERTION_COLUMNS,
    CELL_SUMMARY_COLUMNS,
    MEASUREMENT_COLUMNS,
    CachePolicy,
    GitHubRunClient,
    GitHubTransport,
    RunDataset,
)

ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / "experiment" / "tasks"
scenarios(str(ROOT / "experiment" / "features" / "analysis-dataset.feature"))


@pytest.fixture
def remote_client(tmp_path: Path, fake_pygithub: tuple[MagicMock, MagicMock]):
    gh, http_client = fake_pygithub
    client = GitHubRunClient(
        repo="Archont561/geoai-mcp-eval",
        token="ghp_test_secret",
        cache_dir=tmp_path / "cache",
        transport=GitHubTransport(github_client=gh, http_client=http_client),
    )
    return {"client": client, "http": http_client}


@pytest.fixture
def repository_issue(tmp_path: Path, fake_pygithub: tuple[MagicMock, MagicMock]) -> dict:
    gh, http = fake_pygithub
    return {
        "github": gh,
        "http": http,
        "client": GitHubRunClient(
            repo="org/repo",
            cache_dir=tmp_path / "cache",
            transport=GitHubTransport(github_client=gh, http_client=http),
        ),
    }


# Step definitions follow feature and scenario order; shared steps appear at first use.

# analysis-dataset.feature — A pilot archive supplies tables and trial evidence


@given("an archive of a completed pilot run", target_fixture="archive")
def pilot_archive(packed_pilot_zip: Path) -> Path:
    return packed_pilot_zip


@when("the researcher opens the archive for analysis", target_fixture="dataset")
def open_dataset(archive: Path):
    with RunDataset.from_zip(archive) as dataset:
        yield dataset


@then("the measurement table describes all six trials")
def measurement_table(dataset: RunDataset) -> None:
    assert dataset.run.run_id == "pilot-001"
    table = dataset.measurements_df()
    assert list(table.columns) == list(MEASUREMENT_COLUMNS)
    assert len(table) == 6
    assert set(table["paradigm"]) == {"typed_mcp", "codegen"}
    assert set(table["task_success"]) == {1}


@then("the predicate table contains the expected pilot results")
def predicate_table(dataset: RunDataset) -> None:
    table = dataset.predicates_df(TASKS)
    assert table.shape == (6, 10)
    assert not table.isna().any().any()
    de9im = table[table["task_id"] == "analysis-de9im-001"]
    assert list(de9im["touches"]) == [1, 1]
    for column in ("natural_breaks", "feature_count", "point_axis_order"):
        assert list(de9im[column]) == [0, 0]
    axis = table[table["task_id"] == "prep-axis-order-001"]
    assert list(axis["feature_count"]) == [1, 1]
    assert list(axis["point_axis_order"]) == [1, 1]
    assert list(axis["touches"]) == [0, 0]


@then("the condition summaries report successful trials")
def cell_summaries(dataset: RunDataset) -> None:
    summary = dataset.condition_summary_df()
    assert summary.equals(dataset.cell_summary_df())
    assert list(summary.columns) == list(CELL_SUMMARY_COLUMNS)
    assert len(summary) == 6
    assert all(summary["pass_at_k"])
    assert all(summary["task_success_rate"] == 1.0)
    assert all(summary["predicate_score_median"] == 1.0)


@then("the assertion table describes the graded checks")
def assertion_table(dataset: RunDataset) -> None:
    table = dataset.assertions_df(TASKS)
    assert list(table.columns) == list(ASSERTION_COLUMNS)
    assert len(table) == 8
    assert set(table["tier"]) <= {"trivial", "spatial", "value"}


@then("the researcher can inspect a trial's transcript and deliverable")
def trial_evidence(dataset: RunDataset) -> None:
    handle = dataset.trial("analysis-de9im-001/typed_mcp/semantic_repair/rep-1")
    assert isinstance(handle.transcript, list)
    assert len(handle.transcript) >= 1
    assert handle.deliverable is not None


# analysis-dataset.feature — An unrecognised grading check cannot be classified


@given("a run with a grading check unknown to the task suite", target_fixture="memory_run")
def unknown_assertion_run() -> dict:
    from experiment.domain.run import (
        AssertionResult,
        CostAndProcessMetrics,
        ExperimentRun,
        TokenUsage,
        Treatment,
        TrialKey,
        TrialMeasurement,
        TrialRecord,
    )

    key = TrialKey(
        task_id="analysis-de9im-001", paradigm="codegen", enforcement_level="none", repetition=1
    )
    trial = TrialRecord(
        key=key,
        treatment=Treatment(paradigm="codegen", enforcement_level="none"),
        driver="scripted",
        status="ok",
    )
    measurement = TrialMeasurement.from_assertions(
        key=key,
        assertions=(
            AssertionResult(
                assertion_id="mystery-assertion", tier="spatial", passed=True, detail="ok"
            ),
        ),
        economics=CostAndProcessMetrics(
            wall_seconds=1.5, tokens=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        ),
    )
    run = ExperimentRun(
        run_id="bad-assert",
        stage="pilot",
        trials={key.slug: trial},
        measurements={key.slug: measurement},
    )
    return {"dataset": RunDataset.from_run(run), "key": key}


@when("the researcher requests the predicate and assertion tables", target_fixture="table_errors")
def request_unknown_tables(memory_run: dict) -> list[str]:
    errors = []
    for method in (memory_run["dataset"].predicates_df, memory_run["dataset"].assertions_df):
        try:
            method(TASKS)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


@then("both tables reject the unrecognised check")
def unknown_check_rejected(table_errors: list[str]) -> None:
    assert len(table_errors) == 2
    assert all("mystery-assertion" in error for error in table_errors)


# analysis-dataset.feature — Trial evidence cannot be opened from an in-memory run


@when("the researcher requests its trial evidence", target_fixture="trial_error")
def request_memory_trial(memory_run: dict) -> str:
    try:
        memory_run["dataset"].trial(memory_run["key"])
    except RuntimeError as exc:
        return str(exc)
    return ""


@then("the request explains that an archive is required")
def archive_required(trial_error: str) -> None:
    assert "zip-backed" in trial_error


# analysis-dataset.feature — An empty preparation run yields an empty summary


@given("an empty preparation run", target_fixture="memory_run")
def empty_preparation_run() -> dict:
    from experiment.domain.run import ExperimentRun

    return {"dataset": RunDataset.from_run(ExperimentRun(run_id="empty", stage="preflight"))}


@when("the researcher requests its condition summary", target_fixture="summary")
def request_empty_summary(memory_run: dict):
    return memory_run["dataset"].cell_summary_df()


@then("the summary is empty with the expected columns")
def empty_summary(summary) -> None:
    assert summary.empty
    assert list(summary.columns) == list(CELL_SUMMARY_COLUMNS)


# analysis-dataset.feature — The latest successful run is available for analysis


@given("a repository with a completed pilot run", target_fixture="remote")
def repository_with_run(remote_client: dict) -> dict:
    return remote_client


@when("the researcher lists and loads its latest run")
def list_and_load_latest(remote: dict) -> None:
    remote["runs"] = remote["client"].list_runs(limit=5, branch="main")
    with remote["client"].load_latest(branch="main") as dataset:
        remote["measurement_count"] = len(dataset.measurements_df())


@then("the run's identity and six trial measurements are available")
def run_identity_and_measurements(remote: dict) -> None:
    assert len(remote["runs"]) == 1
    assert remote["runs"][0].database_id == 987654321
    assert remote["runs"][0].head_sha == "deadbeef"
    assert remote["measurement_count"] == 6


@then("the download does not expose credentials to the storage host")
def redirected_download_strips_credentials(remote: dict) -> None:
    http = remote["http"]
    assert http.get.call_count == 2
    assert http.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer ghp_test_secret"
    assert "headers" not in http.get.call_args_list[1].kwargs


# analysis-dataset.feature — A previously downloaded run is reused


@given("a locally cached pilot run", target_fixture="remote")
def cached_run(remote_client: dict) -> dict:
    remote_client["cached_path"] = remote_client["client"].download_run(987654321)
    assert remote_client["http"].get.call_count == 2
    return remote_client


@when("the researcher loads that run again")
def reload_cached_run(remote: dict) -> None:
    with remote["client"].load_run(987654321) as dataset:
        remote["measurement_count"] = len(dataset.measurements_df())


@then("all six trial measurements are available without another download")
def cache_was_used(remote: dict) -> None:
    assert remote["measurement_count"] == 6
    assert remote["http"].get.call_count == 2


# analysis-dataset.feature — A researcher requests a fresh copy


@when("the researcher refreshes that run")
def refresh_cached_run(remote: dict) -> None:
    remote["path"] = remote["client"].download_run(987654321, cache=CachePolicy.REFRESH)


@then("the archive is downloaded again")
def archive_downloaded_again(remote: dict) -> None:
    assert remote["path"].is_file()
    assert remote["http"].get.call_count == 4


# analysis-dataset.feature — A damaged local copy is replaced


@given("a locally cached pilot run that has become damaged", target_fixture="remote")
def damaged_cached_run(remote_client: dict) -> dict:
    cached_run(remote_client)
    remote_client["cached_path"].write_bytes(b"corrupted-not-a-zip")
    return remote_client


@when("the researcher retrieves that run")
def retrieve_damaged_run(remote: dict) -> None:
    remote["path"] = remote["client"].download_run(987654321, cache=CachePolicy.USE)


@then("a fresh archive replaces the damaged copy")
def damaged_copy_replaced(remote: dict) -> None:
    assert remote["path"].is_file()
    assert remote["http"].get.call_count == 4
    with RunArchive.open(remote["path"]) as archive:
        archive.verify_all()


# analysis-dataset.feature — A local archive can be analysed without a network


@when(
    "the researcher opens it directly without connecting to the repository",
    target_fixture="offline",
)
def load_offline(archive: Path, tmp_path: Path) -> dict:
    client = GitHubRunClient(cache_dir=tmp_path / "cache")
    with client.load_zip(archive) as dataset:
        run_id = dataset.run.run_id
    with RunArchive.open(archive) as run_archive:
        wrapped = RunDataset.from_archive(run_archive)
        count = len(wrapped.measurements_df())
    return {"run_id": run_id, "count": count}


@then("the pilot run and its six measurements are available")
def offline_measurements(offline: dict) -> None:
    assert offline == {"run_id": "pilot-001", "count": 6}


# analysis-dataset.feature — A redirected archive download keeps credentials private


@given(
    "a repository that redirects archive downloads to a storage service", target_fixture="redirect"
)
def redirected_repository(
    tmp_path: Path,
    packed_pilot_zip: Path,
    fake_pygithub: tuple[MagicMock, MagicMock],
    respx_mock: respx.MockRouter,
) -> dict:
    gh, _http = fake_pygithub
    artifact = gh.get_repo.return_value.get_workflow_run.return_value.get_artifacts.return_value[0]
    api_route = respx_mock.get(artifact.archive_download_url).mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://blob.example.invalid/sas/987654321.zip"}
        )
    )
    outer = _wrap_in_outer_artifact_zip(packed_pilot_zip, "experiment-run-987654321-deadbeef.zip")
    blob_route = respx_mock.get("https://blob.example.invalid/sas/987654321.zip").mock(
        return_value=httpx.Response(200, content=outer)
    )
    client = GitHubRunClient(
        repo="Archont561/geoai-mcp-eval",
        token="ghp_respx_secret",
        cache_dir=tmp_path / "cache",
        transport=GitHubTransport(github_client=gh),
    )
    return {"client": client, "api": api_route, "blob": blob_route}


@when("the researcher loads the run from the repository")
def load_redirected_run(redirect: dict) -> None:
    with redirect["client"].load_run(987654321) as dataset:
        redirect["count"] = len(dataset.measurements_df())


@then("all six trial measurements are available")
def redirected_measurements(redirect: dict) -> None:
    assert redirect["count"] == 6


@then("repository credentials are absent from the storage request")
def redirect_credentials_protected(redirect: dict) -> None:
    assert redirect["api"].called
    assert redirect["blob"].called
    assert redirect["api"].calls.last.request.headers["authorization"] == "Bearer ghp_respx_secret"
    assert "authorization" not in redirect["blob"].calls.last.request.headers


# analysis-dataset.feature — The pilot suite defines a unique predicate for each grading check


@given("the published pilot task suite")
def published_pilot_suite() -> None:
    """The task suite is checked into the study repository."""


@when("the researcher prepares its grading predicates for analysis", target_fixture="predicates")
def prepare_pilot_predicates() -> dict[str, str]:
    from experiment.analysis import load_predicates

    return load_predicates(TASKS)


@then("the four pilot grading checks map to distinct analysis predicates")
def pilot_predicates_are_unique(predicates: dict[str, str]) -> None:
    assert predicates == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
        "natural-breaks-assignments": "natural_breaks",
    }
    assert len(predicates) == len(set(predicates.values()))


# analysis-dataset.feature — Repository credentials are rejected


@given("a repository that rejects the researcher's credentials")
def rejected_repository_credentials(repository_issue: dict) -> None:
    from github import GithubException

    repository_issue["github"].get_repo.side_effect = GithubException(
        401, {"message": "Bad credentials"}, None
    )


@when("the researcher lists its runs")
def list_repository_runs(repository_issue: dict) -> None:
    from experiment.analysis import GitHubRunError

    try:
        repository_issue["runs"] = repository_issue["client"].list_runs()
    except GitHubRunError as exc:
        repository_issue["error"] = str(exc)


@then("the repository access error is reported")
def repository_access_error(repository_issue: dict) -> None:
    assert "GitHub API error" in repository_issue["error"]


# analysis-dataset.feature — No successful run is available


@given("a repository without a completed successful run")
def repository_without_runs(repository_issue: dict) -> None:
    repo = repository_issue["github"].get_repo.return_value
    repo.get_workflow.return_value.get_runs.return_value = []


@when("the researcher requests the latest run")
def request_latest_repository_run(repository_issue: dict) -> None:
    from experiment.analysis import GitHubRunError

    try:
        repository_issue["client"].load_latest()
    except GitHubRunError as exc:
        repository_issue["error"] = str(exc)


@then("the absence of a successful run is reported")
def no_successful_run_error(repository_issue: dict) -> None:
    assert "no successful completed runs" in repository_issue["error"]


# analysis-dataset.feature — A run has no matching experiment archive


@given("a run without an experiment archive")
def run_without_archive(repository_issue: dict) -> None:
    repo = repository_issue["github"].get_repo.return_value
    repo.get_workflow_run.return_value.get_artifacts.return_value = []


@when("the researcher retrieves its archive")
def retrieve_repository_archive(repository_issue: dict) -> None:
    from experiment.analysis import GitHubRunError

    try:
        repository_issue["archive"] = repository_issue["client"].download_run(987654321)
    except GitHubRunError as exc:
        repository_issue["error"] = str(exc)


@then("the missing experiment archive is reported")
def missing_experiment_archive_error(repository_issue: dict) -> None:
    assert "no experiment-run" in repository_issue["error"]


# analysis-dataset.feature — An archive cannot be downloaded safely


@given(parsers.parse("a run whose archive download encounters {problem}"))
def archive_download_problem(repository_issue: dict, problem: str) -> None:
    http = repository_issue["http"]
    http.get.side_effect = None
    if problem == "a network failure":
        http.get.side_effect = httpx.ConnectError("network down")
        return
    responses = {
        "invalid archive contents": httpx.Response(200, content=b"not-a-zip"),
        "a missing download": httpx.Response(404),
        "an incomplete redirect": httpx.Response(302),
    }
    http.get.return_value = responses[problem]


@then(parsers.parse("the download reports {explanation}"))
def archive_download_error(repository_issue: dict, explanation: str) -> None:
    expected = {
        "an artifact download failure": "artifact download failed",
        "an invalid archive": "not a valid zip",
        "an unavailable download": "HTTP 404",
        "an incomplete redirect": "missing Location",
    }
    assert expected[explanation] in repository_issue["error"]


# analysis-dataset.feature — Repository identity is unavailable


@given("no repository is configured for analysis")
def no_repository_configured(
    repository_issue: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from experiment.adapters import paths

    monkeypatch.setattr(paths, "find_repo_root", lambda: tmp_path)
    repository_issue["client"] = GitHubRunClient(
        cache_dir=tmp_path / "cache",
        transport=GitHubTransport(
            github_client=repository_issue["github"], http_client=repository_issue["http"], env={}
        ),
    )


@then("the missing repository configuration is reported")
def missing_repository_error(repository_issue: dict) -> None:
    assert "repository not configured" in repository_issue["error"]


# analysis-dataset.feature — A local checkout identifies its repository


@given("a checkout with a configured GitHub repository")
def checkout_with_repository(
    repository_issue: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_repository_configured(repository_issue, tmp_path, monkeypatch)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/Archont561/geoai-mcp-eval.git\n',
        encoding="utf-8",
    )
    repo = repository_issue["github"].get_repo.return_value
    repo.get_workflow.return_value.get_runs.return_value = []


@then("the configured repository is used without requiring a command-line client")
def configured_checkout_repository(repository_issue: dict) -> None:
    assert repository_issue["runs"] == []
    repository_issue["github"].get_repo.assert_called_once_with("Archont561/geoai-mcp-eval")


# analysis-dataset.feature — A direct archive download uses the configured environment credentials


@given("a direct archive download with environment credentials")
def direct_download_with_environment_credentials(
    repository_issue: dict, tmp_path: Path, packed_pilot_zip: Path
) -> None:
    http = repository_issue["http"]
    http.get.side_effect = None
    http.get.return_value = httpx.Response(200, content=packed_pilot_zip.read_bytes())
    repository_issue["client"] = GitHubRunClient(
        cache_dir=tmp_path / "cache",
        transport=GitHubTransport(
            github_client=repository_issue["github"],
            http_client=http,
            env={"GH_TOKEN": "gho_env_token", "GITHUB_REPOSITORY": "Archont561/geoai-mcp-eval"},
        ),
    )


@then("the archive is saved and the credentials are sent to the repository")
def direct_archive_uses_environment_credentials(repository_issue: dict) -> None:
    assert repository_issue["archive"].name == "experiment-run-987654321-deadbeef.zip"
    assert repository_issue["http"].get.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer gho_env_token"
    )


# analysis-dataset.feature — Downloaded runs have a default local cache


@given("the default analysis settings")
def default_analysis_settings() -> None:
    """Use the client's default cache location."""


@when("the researcher prepares the run client", target_fixture="default_run_client")
def prepare_default_run_client() -> GitHubRunClient:
    return GitHubRunClient()


@then("the local cache is in the study checkout")
def default_cache_in_checkout(default_run_client: GitHubRunClient) -> None:
    from experiment.adapters import paths

    assert default_run_client.cache_dir == paths.find_repo_root() / ".cache" / "gh-runs"
