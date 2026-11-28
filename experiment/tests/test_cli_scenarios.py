"""Step definitions and scenario bindings for the experiment CLI features.

The Gherkin specifications under ``experiment/features/`` use plain GIS-researcher
domain prose (following ``.agents/skills/bdd-scenarios/SKILL.md``). These step
bindings translate each declarative step into real Typer CLI invocations against
``experiment.cli._loader.app``.
"""

from __future__ import annotations

import json
import shlex
import sys
import types
from pathlib import Path

import pytest
from cli_harness import write_jenks_artifact
from cli_harness import write_point_artifact as _write_point
from cli_harness import write_relation_artifact as _write_relation
from pytest_bdd import given, parsers, scenarios, then, when
from rich.text import Text
from typer.testing import CliRunner

from experiment.cli._loader import app

FEATURE_DIR = Path(__file__).resolve().parents[1] / "features"


class _Substitutions(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def run_cli(cli: CliRunner, command: str, **substitutions: str) -> dict:
    """Invoke the mounted Typer application with a shell-like command line."""
    expanded = command.format_map(_Substitutions(substitutions))
    result = cli.invoke(app, shlex.split(expanded))
    raised = "" if isinstance(result.exception, SystemExit | None) else str(result.exception)
    return {
        "exit_code": result.exit_code,
        "output": result.output,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "raised": raised,
        "command": expanded,
    }


def _plain_output(result: dict) -> str:
    return Text.from_ansi(result["output"].replace("\r\n", "\n")).plain


def _unwrapped_output(result: dict) -> str:
    return _plain_output(result).replace("\n", "")


def _long_path(parent: Path, leaf: str) -> Path:
    return parent / ("long-directory-name-for-wrapping-" * 4) / leaf


_PYQGIS_AVAILABLE = {
    "qgis": "4.2",
    "gdal": "x",
    "geos": "y",
    "proj": "z",
    "python": sys.version.split()[0],
}


def _stub_arm_b_chat(monkeypatch: pytest.MonkeyPatch, usage: dict | None) -> None:
    from experiment.adapters import _ollama_chat

    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    payload: dict = {
        "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}]
    }
    if usage is not None:
        payload["usage"] = usage
    monkeypatch.setattr(_ollama_chat, "chat_completions_sdk", lambda *_a, **_kw: payload)


def _read_transcript(output: Path) -> list[dict]:
    path = output / "cell-B-analysis-de9im-001-r1" / "transcript.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


for _feature in (
    "command-line.feature",
    "pilot-suite.feature",
    "prototype-runs.feature",
    "workflow.feature",
    "qgis-sandbox.feature",
):
    scenarios(str(FEATURE_DIR / _feature))


def setup_workflow_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, invalid: bool
) -> dict:
    from experiment.adapters import subprocess_runner
    from experiment.adapters.task_suite import ValidationIssue, ValidationReport
    from experiment.services import tasks, workflow

    (tmp_path / "pixi.lock").write_text("lock-bytes", encoding="utf-8")
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    validated = []
    real_validate = tasks.validate_suite

    def validate(root):
        validated.append(root)
        if invalid:
            return ValidationReport(
                task_count=0,
                traps_found=frozenset(),
                issues=(ValidationIssue(path="suite", message="missing trap"),),
            )
        return real_validate(root)

    def fail_passthrough(cmd, **_kwargs):
        raise AssertionError(f"preflight must not spawn CLI subprocess: {cmd}")

    monkeypatch.setattr(subprocess_runner, "run_passthrough", fail_passthrough)
    monkeypatch.setattr(workflow.tasks_service, "validate_suite", validate)
    monkeypatch.setattr(subprocess_runner, "soft_version", lambda _cmd, _cwd: "v1.0.0")
    return {"root": tmp_path, "validated": validated}


# Step definitions follow feature and scenario order; shared steps appear at first use.

# command-line.feature — Researcher views the top-level study command groups


@when("I ask the study tool for top-level help", target_fixture="result")
def ask_for_help(cli: CliRunner) -> dict:
    return run_cli(cli, "--help")


@then(parsers.parse('the help lists the "{group}" capability group'))
def help_lists_group(result: dict, group: str) -> None:
    assert group in result["output"]


# command-line.feature — Smoke check confirms the study tool and task suite are wired together


@when("I run the study smoke check", target_fixture="result")
def run_smoke_check(cli: CliRunner) -> dict:
    return run_cli(cli, "run smoke")


@then("the action succeeds")
def action_succeeds(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]


@then(parsers.parse('the researcher sees "{expected}"'))
def researcher_sees(result: dict, expected: str) -> None:
    assert expected in _plain_output(result), result["output"]


# command-line.feature — Configuration is visible without revealing a credential


@given("a configured model-service credential", target_fixture="configured_secret")
def configured_model_credential(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "sk-or-v1-must-never-appear-in-cli-output"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    return secret


@when("I inspect the configuration in both display formats", target_fixture="config_displays")
def inspect_both_config_formats(cli: CliRunner) -> list[dict]:
    return [run_cli(cli, "env config --json"), run_cli(cli, "env config")]


@then("both displays keep the credential secret")
def config_displays_keep_secret(config_displays: list[dict], configured_secret: str) -> None:
    for result in config_displays:
        assert result["exit_code"] == 0, result["output"]
        assert configured_secret not in result["output"]
    parsed = json.loads(config_displays[0]["stdout"])
    assert "backends" in parsed and "experiment" in parsed
    assert parsed["backends"]["free-open"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert "experiment" in config_displays[1]["output"]


# command-line.feature — A missing configuration file is rejected


@given("a configuration file that does not exist", target_fixture="missing_config")
def nonexistent_config(tmp_path: Path) -> Path:
    return tmp_path / "missing.toml"


@when("I inspect that configuration", target_fixture="result")
def inspect_missing_config(cli: CliRunner, missing_config: Path) -> dict:
    return run_cli(cli, f"env config --config {missing_config}")


@then(parsers.parse("the action exits with status {code:d}"))
def action_exits_with_status(result: dict, code: int) -> None:
    assert result["exit_code"] == code, result["output"]


# command-line.feature — Tool and runtime diagnostics are available for automated analysis


@given("simulated geographic tool and runtime diagnostics")
def simulated_setup_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    from experiment.services import mcp_selftest, qgis

    async def fake_selftest() -> list[tuple[str, str, str]]:
        return [("list_tools", "5 tools", "ok")]

    monkeypatch.setattr(mcp_selftest, "selftest_rows", fake_selftest)
    monkeypatch.setattr(qgis, "qgis_versions", lambda: {"qgis": "4.2.3", "python": "3.13"})


@when("I request machine-readable setup diagnostics", target_fixture="setup_diagnostics")
def request_setup_diagnostics(cli: CliRunner) -> list[dict]:
    return [
        run_cli(cli, "env mcp-ops --json"),
        run_cli(cli, "env mcp-selftest --json"),
        run_cli(cli, "env qgis check --json"),
    ]


@then("the diagnostics identify the tools and available runtime")
def diagnostics_identify_setup(setup_diagnostics: list[dict]) -> None:
    assert all(item["exit_code"] == 0 for item in setup_diagnostics), setup_diagnostics
    ops, selftest, qgis = [json.loads(item["stdout"]) for item in setup_diagnostics]
    assert any(item["name"] == "relate_de9im" for item in ops)
    assert selftest == [{"step": "list_tools", "result": "5 tools", "detail": "ok"}]
    assert qgis == {"available": True, "versions": {"qgis": "4.2.3", "python": "3.13"}}


# command-line.feature — An unavailable GIS runtime has a machine-readable verdict


@given("an environment without the GIS runtime")
def env_without_pyqgis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "qgis", None)


@when("I request machine-readable GIS runtime diagnostics", target_fixture="result")
def request_gis_diagnostics(cli: CliRunner) -> dict:
    return run_cli(cli, "env qgis check --json")


@then("the diagnostics report that the runtime is unavailable")
def runtime_unavailable_diagnostics(result: dict) -> None:
    assert result["exit_code"] == 3
    assert json.loads(result["stdout"]) == {"available": False, "versions": None}


# command-line.feature — A researcher selects configuration through the environment


@given("a study configuration selected in the environment", target_fixture="study_config_case")
def configured_environment_selection(tmp_path: Path) -> dict:
    path = tmp_path / "study.toml"
    path.write_text('[experiment]\ndefault_driver = "ollama"\n', encoding="utf-8")
    return {"path": path, "selection": "through the environment"}


@when("the researcher loads the selected configuration")
@when("the researcher loads the default configuration")
def load_selected_study_config(study_config_case: dict) -> None:
    from experiment.adapters import config

    path, selection = study_config_case["path"], study_config_case["selection"]
    try:
        if selection == "directly":
            study_config_case["result"] = config.load_config(path, env={})
        elif selection == "through the environment":
            study_config_case["result"] = config.load_config(env={"EXPERIMENT_CONFIG": str(path)})
        else:
            study_config_case["result"] = config.load_config(env={})
    except config.ConfigError as error:
        study_config_case["error"] = error


@then("the configured execution driver is used")
def selected_driver_is_used(study_config_case: dict) -> None:
    from experiment.domain.run import Driver

    assert study_config_case["result"].experiment.default_driver is Driver.OLLAMA


# command-line.feature — Explicitly selected missing configuration is reported


@given(
    parsers.parse("a missing study configuration selected {selection}"),
    target_fixture="study_config_case",
)
def missing_selected_config(tmp_path: Path, selection: str) -> dict:
    return {"path": tmp_path / "missing.toml", "selection": selection}


@then("the missing configuration is reported")
def selected_config_missing(study_config_case: dict) -> None:
    error = str(study_config_case["error"])
    if study_config_case["selection"] == "through the environment":
        assert "EXPERIMENT_CONFIG" in error
    else:
        assert "not found" in error


# command-line.feature — An absent default configuration uses built-in defaults


@given("no default study configuration file", target_fixture="study_config_case")
def missing_default_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from experiment.adapters import config

    path = tmp_path / "missing.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    return {"path": path, "selection": "default"}


@then("the built-in local model settings are used")
def fallback_config_is_used(study_config_case: dict) -> None:
    config = study_config_case["result"]
    assert config.experiment.default_backend == "local"
    assert config.backends == {}


# command-line.feature — Unrecognized study command is rejected


@when("I invoke an unknown study command", target_fixture="result")
def invoke_unknown_command(cli: CliRunner) -> dict:
    return run_cli(cli, "no-such-command")


@then("the action is refused")
def action_refused(result: dict) -> None:
    assert result["exit_code"] != 0, result["output"]


@then("the explanation identifies the unrecognized command")
def unknown_command_explained(result: dict) -> None:
    assert "No such command" in _plain_output(result)


# command-line.feature — Capability group invoked without an action prompts for a sub-action


@when("I invoke the tasks capability group without choosing an action", target_fixture="result")
def invoke_tasks_group_bare(cli: CliRunner) -> dict:
    return run_cli(cli, "tasks")


@then("the explanation asks for an action")
def missing_action_explained(result: dict) -> None:
    assert "Missing command" in _plain_output(result)


# pilot-suite.feature — Shipped pilot suite lists all tasks


@when("I list the tasks in the pilot suite", target_fixture="result")
def list_pilot_tasks(cli: CliRunner, suite: dict) -> dict:
    return run_cli(cli, f"tasks ls --root {suite['path']}")


# pilot-suite.feature — Shipped pilot suite displays details for a chosen task


@when(parsers.parse('I inspect task "{task_id}" in the pilot suite'), target_fixture="result")
def inspect_pilot_task(cli: CliRunner, suite: dict, task_id: str) -> dict:
    return run_cli(cli, f"tasks show {task_id} --root {suite['path']}")


# pilot-suite.feature — Automated analysis can read task details and suite validation


@given("the pilot task suite is available for automated analysis")
def pilot_suite_available_for_analysis(suite: dict) -> None:
    assert suite["root"].is_dir()


@when("I request machine-readable task details and validation", target_fixture="task_reports")
def machine_readable_task_reports(cli: CliRunner, suite: dict) -> dict:
    return {
        "task": run_cli(cli, f"tasks show analysis-de9im-001 --json --root {suite['path']}"),
        "validation": run_cli(cli, f"tasks validate --json --root {suite['path']}"),
    }


@then("both reports identify a valid pilot task suite")
def machine_readable_task_reports_are_valid(task_reports: dict) -> None:
    for report in task_reports.values():
        assert report["exit_code"] == 0, report["output"]
    task = json.loads(task_reports["task"]["stdout"])
    validation = json.loads(task_reports["validation"]["stdout"])
    assert task["id"] == "analysis-de9im-001"
    assert isinstance(task["assertions"], list)
    assert validation["passed"] is True
    assert validation["task_count"] >= 3


# pilot-suite.feature — A researcher can inspect a valid task beside a damaged task


@given("a pilot task suite with a damaged task definition", target_fixture="suite")
def suite_with_damaged_task(suite: dict) -> dict:
    (suite["root"] / "aaa-broken.yaml").write_text("id: [unclosed\n", encoding="utf-8")
    return suite


# pilot-suite.feature — Listing a suite with a damaged task explains the failure


@then("the explanation identifies the damaged task definition")
def explanation_damaged_task(result: dict) -> None:
    reported = result["output"] + result["stderr"] + result["raised"]
    assert "aaa-broken.yaml" in reported
    assert "cannot parse YAML" in reported


# pilot-suite.feature — Complete pilot suite passes validation


@when("I validate the pilot task suite", target_fixture="result")
@when("I validate that task suite", target_fixture="result")
def validate_pilot_suite(cli: CliRunner, suite: dict) -> dict:
    return run_cli(cli, f"tasks validate --root {suite['path']}")


@then("the report confirms 3 tasks are valid and all pilot traps are covered")
def report_confirms_valid_suite(result: dict) -> None:
    assert " ".join(result["stdout"].split()) == (
        "Task suite valid: 3 tasks; pilot traps covered: "
        "crs-axis-order, jenks-classification, topology-de9im"
    )


# pilot-suite.feature — Task suite missing its validation schema is rejected


@given("a pilot task suite missing its validation schema", target_fixture="suite")
def suite_without_schema(suite: dict) -> dict:
    (suite["root"] / "schema-v1.json").unlink()
    return suite


@then("the explanation states that the schema cannot be read")
def explanation_schema_unreadable(result: dict) -> None:
    assert "cannot read schema" in result["stdout"]


# pilot-suite.feature — Valid task outputs pass the determinism gate


@given("valid reference outputs for every pilot task", target_fixture="artifacts")
def valid_reference_outputs(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    _write_point(root)
    _write_relation(root)
    write_jenks_artifact(root)
    return root


@when(parsers.parse('I run the determinism gate for task "{task_id}"'), target_fixture="result")
def run_determinism_gate(cli: CliRunner, artifacts: Path, suite: dict, task_id: str) -> dict:
    result = run_cli(
        cli,
        f"score determinism {task_id} --artifacts-dir {artifacts / task_id} --root {suite['path']}",
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    return {**result, "report": payload}


@then("the determinism report states the task passed")
def determinism_passed(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    assert result["report"]["passed"] is True


@then("the determinism report covers three repeated checks")
def determinism_covers_three(result: dict) -> None:
    report = result["report"]
    assert report["required_runs"] == 3
    assert report["consistent"] is True
    assert [run["status"] for run in report["run_results"]] == ["passed"] * 3


# pilot-suite.feature — Missing task outputs fail the determinism gate


@given(parsers.parse('no outputs for task "{task_id}"'), target_fixture="artifacts")
def no_outputs(tmp_path: Path, task_id: str) -> Path:
    return tmp_path / "missing"


@then("the determinism report states the task failed")
def determinism_failed(result: dict) -> None:
    assert result["exit_code"] == 1, result["output"]
    assert result["report"]["passed"] is False


# pilot-suite.feature — Determinism gate refuses an unknown task identifier


@then("the explanation states that the task identifier is unknown")
def explanation_unknown_task(result: dict) -> None:
    reported = result["output"] + result["stderr"] + result["raised"]
    assert "unknown task ID" in reported


# prototype-runs.feature — Researcher lists the typed GIS operation catalogue


@when("I inspect the typed GIS operation catalogue", target_fixture="result")
def inspect_gis_catalogue(cli: CliRunner) -> dict:
    return run_cli(cli, "env mcp-ops")


@then("the catalogue includes the boundary relation operation")
def catalogue_includes_boundary_relation(result: dict) -> None:
    assert "relate_de9im" in result["output"]


@then("the catalogue reports the total number of operations")
def catalogue_reports_total(result: dict) -> None:
    assert "14 ops" in result["output"]


# prototype-runs.feature — Self-test verifies the typed GIS service end to end


@when("I run the typed GIS service self-test", target_fixture="result")
def run_mcp_selftest(cli: CliRunner) -> dict:
    return run_cli(cli, "env mcp-selftest")


@then("the self-test reports the tool count and filtered Poland feature")
def selftest_reports_poland(result: dict) -> None:
    for expected in ("list_tools", "14 tools", "filter_features POL", "1 feature", "Poland"):
        assert expected in result["output"], result["output"]


@then("the self-test reports the boundary relationship between Poland and Czechia")
def selftest_reports_relation(result: dict) -> None:
    assert "relate_de9im POL×CZE" in result["output"]
    assert "touches" in result["output"]
    assert "FF2F11212" in result["output"]


# prototype-runs.feature — A researcher repeats a typed-tool run and inspects its archive


@given("a fresh experiment output folder", target_fixture="output")
def fresh_output_folder(tmp_path: Path) -> Path:
    return tmp_path / "out"


@when("I run two repetitions of a typed-tool task and save an archive", target_fixture="result")
def run_two_repetitions(cli: CliRunner, output: Path) -> dict:
    return run_cli(
        cli,
        f"run mcp --driver scripted --task analysis-de9im-001 --repetitions 2 "
        f"--cache --output-dir {output} --pack-zip",
    )


@then("both repetitions have separate scores and appear in both reports")
def repeated_trials_are_recorded(cli: CliRunner, output: Path, result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    for repetition in (1, 2):
        assert (output / f"cell-A-analysis-de9im-001-r{repetition}" / "score.json").is_file()
    evaluated = run_cli(cli, f"score eval {output} --json")
    displayed = run_cli(cli, f"score show {output} --json")
    archive = output.parent / f"experiment-run-{output.name}.zip"
    inspected = run_cli(cli, f"archive inspect {archive} --json")
    for report in (evaluated, displayed, inspected):
        assert report["exit_code"] == 0, report["output"]
    score = json.loads(evaluated["stdout"])
    assert score["total"] == json.loads(displayed["stdout"])["total"] == 2
    assert {cell["repetition"] for cell in score["cells"]} == {1, 2}
    details = json.loads(inspected["stdout"])
    assert details["trial_count"] == 2
    assert {trial["repetition"] for trial in details["trials"]} == {1, 2}


# prototype-runs.feature — A run cannot request zero repetitions


@when("I request a run with zero repetitions", target_fixture="result")
def request_zero_repetitions(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"run mcp --repetitions 0 --output-dir {output}")


@then("the explanation says repetitions must be positive")
def repetitions_must_be_positive(result: dict) -> None:
    assert "--repetitions must be a positive integer" in _plain_output(result)


# prototype-runs.feature — An unknown enforcement level is rejected


@when("I request a typed-tool run with an unknown enforcement level", target_fixture="result")
def request_unknown_enforcement(cli: CliRunner) -> dict:
    return run_cli(cli, "run mcp --task analysis-de9im-001 --enforce N9")


@then("the explanation identifies the invalid enforcement level")
def invalid_enforcement_explained(result: dict) -> None:
    assert "N9" in (result["output"] + result["raised"])


# prototype-runs.feature — A saved run can be scored and displayed in both forms


@given("a completed typed-tool run saved as an archive", target_fixture="scored_run")
def typed_run_archive(cli: CliRunner, tmp_path: Path) -> dict:
    output = tmp_path / "mcp-score"
    result = run_cli(
        cli, f"run mcp --task analysis-de9im-001 --enforce N2 --pack-zip --output-dir {output}"
    )
    assert result["exit_code"] == 0, result["output"]
    return {"output": output, "archive": output.parent / f"experiment-run-{output.name}.zip"}


@when("I score and display the archived run and score its output folder")
def score_archive_and_folder(cli: CliRunner, scored_run: dict) -> None:
    archive = scored_run["archive"]
    output = scored_run["output"]
    scored_run["results"] = [
        run_cli(cli, f"score eval {archive}"),
        run_cli(cli, f"score show {archive}"),
        run_cli(cli, f"score eval {output} --json"),
    ]


@then("both forms report that the task passed")
def archive_and_folder_scores_pass(scored_run: dict) -> None:
    results = scored_run["results"]
    assert all(result["exit_code"] == 0 for result in results), results
    assert all("analysis-de9im-001" in result["output"] for result in results[:2])
    assert json.loads(results[2]["stdout"])["passed"] == 1
    from experiment.adapters.run_archive import RunArchive

    inspected = run_cli(CliRunner(), f"archive inspect {scored_run['archive']}")
    assert inspected["exit_code"] == 0 and "syntactic" in inspected["output"]
    with RunArchive.open(scored_run["archive"]) as archive:
        assert "analysis-de9im-001/typed_mcp/syntactic/rep-1" in archive.run.trials


# prototype-runs.feature — Scripted single-task run produces a scored trial with a study disclaimer


@when(
    parsers.parse('I run a scripted benchmark for task "{task_id}" in code-generation mode'),
    target_fixture="result",
)
def run_scripted_codegen(cli: CliRunner, output: Path, task_id: str) -> dict:
    return run_cli(cli, f"run codegen --driver scripted --task {task_id} --output-dir {output}")


@then("the run summary reports one of one trials passed the oracle")
def run_reports_one_of_one(result: dict) -> None:
    assert "1/1 trials oracle-passed" in result["output"]


@then("the output folder holds a run summary")
def output_holds_summary(output: Path) -> None:
    assert (output / "summary.json").is_file()


@then("the output warns that this is not a study result")
def output_warns_not_study(result: dict) -> None:
    assert "pipeline verification only, not a study result." in result["output"]


# prototype-runs.feature — Completed run can be rescored and detects corrupted results


@when("I rescore that completed run", target_fixture="rescored")
def rescore_run(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"score eval {output}")


@then("the rescore reports one of one trials passed the oracle")
def rescore_passed_one(rescored: dict) -> None:
    assert rescored["exit_code"] == 0, rescored["output"]
    assert "1/1 trials oracle-passed" in rescored["output"]


@then("displaying the run shows its oracle verdicts")
def display_shows_verdicts(cli: CliRunner, output: Path) -> None:
    shown = run_cli(cli, f"score show {output}")
    assert shown["exit_code"] == 0, shown["output"]
    assert "Oracle scores" in shown["output"]


@when("I corrupt the saved result and rescore again", target_fixture="rescored")
def corrupt_and_rescore(cli: CliRunner, output: Path) -> dict:
    path = output / "cell-B-analysis-de9im-001-r1" / "result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result.update({"relation": "disjoint", "de9im": "FF*FF****"})
    path.write_text(json.dumps(result), encoding="utf-8")
    return run_cli(cli, f"score eval {output}")


@then("the rescore reports zero trials passed the oracle")
def rescore_zero_passed(rescored: dict) -> None:
    assert rescored["exit_code"] == 0, rescored["output"]
    assert "0/1 trials oracle-passed" in rescored["output"]
    assert "✗" in rescored["output"]


# prototype-runs.feature — Scoring an empty output folder fails clearly


@given("an empty experiment output folder with a long path", target_fixture="output")
def empty_long_output_folder(tmp_path: Path) -> Path:
    return _long_path(tmp_path, "out")


@when("I attempt to score that empty output folder", target_fixture="result")
def score_empty_folder(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"score eval {output}")


@then("the explanation states that no trials were found")
def explanation_no_cells(result: dict, output: Path) -> None:
    assert f"no trials under {output}" in _unwrapped_output(result)


# prototype-runs.feature — Displaying scores for a folder without a summary fails clearly


@when("I attempt to display scores for that folder", target_fixture="result")
def show_empty_folder(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"score show {output}")


@then("the explanation states that the summary is missing")
def explanation_summary_missing(result: dict, output: Path) -> None:
    assert f"missing {output / 'summary.json'}" in _unwrapped_output(result)


# prototype-runs.feature — Unknown execution driver is refused


@when(parsers.parse('I request a run using unknown driver "{driver}"'), target_fixture="result")
def request_unknown_driver(cli: CliRunner, output: Path, driver: str) -> dict:
    return run_cli(cli, f"run all --driver {driver} --output-dir {output}")


@then("the explanation identifies the supported execution drivers")
def execution_drivers_explained(result: dict) -> None:
    assert "--driver must be one of scripted, ollama" in _plain_output(result)


@then("no output folder is created")
def no_output_folder(output: Path) -> None:
    assert not output.exists()


# prototype-runs.feature — Unknown execution driver preserves colored terminal diagnostics


@given("a terminal that requests colored output")
def terminal_requests_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("NO_COLOR", raising=False)


@then("the output includes terminal color styling")
def output_includes_color(result: dict) -> None:
    assert "\x1b[" in result["output"], result["output"]


# prototype-runs.feature — Code-generation runs refuse typed-tool enforcement levels


@when(
    "I request a code-generation run with a typed-tool enforcement level",
    target_fixture="result",
)
def request_codegen_with_enforce(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"run codegen --enforce N3 --output-dir {output}")


# prototype-runs.feature — Unknown model backend profile is refused


@when(parsers.parse('I request a run using unknown backend "{backend}"'), target_fixture="result")
def request_unknown_backend(cli: CliRunner, output: Path, backend: str) -> dict:
    return run_cli(cli, f"run all --backend {backend} --output-dir {output}")


@then("the explanation identifies the unknown backend")
def unknown_backend_explained(result: dict) -> None:
    assert "config: unknown backend 'bogus'" in _plain_output(result)


# prototype-runs.feature — Hosted model backend without credentials is refused before starting


@given("the hosted backend has no API key configured")
def hosted_backend_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@when("I request a model run on the hosted backend", target_fixture="result")
def request_hosted_model_run(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"run all --driver ollama --backend free-open --output-dir {output}")


@then("the explanation identifies the missing hosted-service credential")
def missing_credential_explained(result: dict) -> None:
    assert "environment variable OPENROUTER_API_KEY is unset" in _plain_output(result)


# prototype-runs.feature — Non-positive per-trial token budget is refused before starting


@when("I request a run with a zero token budget per trial", target_fixture="result")
def request_zero_token_budget(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"run all --max-trial-tokens 0 --output-dir {output}")


@then("the explanation says the token budget must be positive")
def token_budget_explained(result: dict) -> None:
    assert "--max-trial-tokens must be a positive integer" in _plain_output(result)


# prototype-runs.feature — Current and earlier token-budget options reject the same invalid value


@when(
    "I request invalid trial budgets using the current and earlier options",
    target_fixture="budget_aliases",
)
def request_both_budget_spellings(cli: CliRunner, output: Path) -> list[dict]:
    return [
        run_cli(cli, f"run all {option} 0 --output-dir {output}")
        for option in ("--max-trial-tokens", "--max-cell-tokens")
    ]


@then("both options report the same invalid-budget explanation")
def both_budget_spellings_rejected(budget_aliases: list[dict]) -> None:
    for result in budget_aliases:
        assert result["exit_code"] == 2
        assert "--max-trial-tokens must be a positive integer" in _plain_output(result)


# prototype-runs.feature — Model token counts are recorded in the transcript and run records


@given(
    parsers.parse("a simulated model endpoint reporting {inp:d} input and {out:d} output tokens")
)
def simulated_endpoint_with_usage(monkeypatch: pytest.MonkeyPatch, inp: int, out: int) -> None:
    _stub_arm_b_chat(
        monkeypatch,
        {"prompt_tokens": inp, "completion_tokens": out, "total_tokens": inp + out},
    )


@when(
    parsers.parse('I run a model-driven code-generation trial for task "{task_id}"'),
    target_fixture="result",
)
def run_model_codegen_cell(cli: CliRunner, output: Path, task_id: str) -> dict:
    return run_cli(cli, f"run codegen --driver ollama --task {task_id} --output-dir {output}")


@then(
    parsers.parse("the transcript records {inp:d} input and {out:d} output tokens without warnings")
)
def transcript_records_tokens(output: Path, inp: int, out: int) -> None:
    entries = _read_transcript(output)
    assistant = [e for e in entries if e.get("role") == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["usage"] == {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
    }
    assert not any(e.get("event") == "usage_warning" for e in entries)
    summaries = [e for e in entries if e.get("event") == "usage_summary"]
    assert len(summaries) == 1
    assert summaries[0]["usage"]["total_tokens"] == inp + out


@then(
    parsers.parse(
        "the run records report totals of {inp:d} input, {out:d} output, and {tot:d} total tokens"
    )
)
def run_records_totals(output: Path, inp: int, out: int, tot: int) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for usage in (summary["usage"], manifest["totals"]["usage"]):
        assert usage["input_tokens"] == inp
        assert usage["output_tokens"] == out
        assert usage["total_tokens"] == tot
        assert usage["cells_with_usage"] == 1
        assert usage["cells_missing_usage"] == 0


# prototype-runs.feature — Missing token usage is recorded as unavailable with an explicit warning


@given("a simulated model endpoint reporting no token usage")
def simulated_endpoint_no_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_arm_b_chat(monkeypatch, None)


@then("the transcript records unavailable usage with an explicit warning")
def transcript_unavailable_usage(output: Path) -> None:
    entries = _read_transcript(output)
    assistant = [e for e in entries if e.get("role") == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["usage"] is None
    warnings = [e for e in entries if e.get("event") == "usage_warning"]
    assert len(warnings) >= 1
    assert "did not report token usage" in warnings[0]["warning"]


@then(
    parsers.parse(
        "the run records report unavailable token totals with {missing:d} missing-usage trial"
    )
)
def run_records_unavailable_totals(output: Path, missing: int) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for usage in (summary["usage"], manifest["totals"]["usage"]):
        assert usage["input_tokens"] is None
        assert usage["output_tokens"] is None
        assert usage["total_tokens"] is None
        assert usage["cells_missing_usage"] == missing
        assert usage["warnings"]


# prototype-runs.feature — Exceeding the trial token budget aborts cleanly before executing code


@when(
    parsers.parse(
        'I run a model-driven code-generation trial for task "{task_id}" '
        "with a budget of {cap:d} tokens"
    ),
    target_fixture="result",
)
def run_model_codegen_with_cap(cli: CliRunner, output: Path, task_id: str, cap: int) -> dict:
    return run_cli(
        cli,
        f"run codegen --driver ollama --task {task_id} "
        f"--max-cell-tokens {cap} --output-dir {output}",
    )


@then("the trial stops for exceeding the token budget without running generated code")
def cell_aborted_token_budget(output: Path) -> None:
    cell_dir = output / "cell-B-analysis-de9im-001-r1"
    assert not (cell_dir / "result.json").exists()
    entries = _read_transcript(output)
    assert not any(e.get("role") == "tool_result" for e in entries)
    aborts = [e for e in entries if e.get("event") == "token_cap_exceeded"]
    assert len(aborts) == 1
    assert aborts[0]["reason"] == "token_cap_exceeded"
    score = json.loads((cell_dir / "score.json").read_text(encoding="utf-8"))
    assert score["meta"]["status"] == "aborted"
    assert score["meta"]["abort_reason"] == "token_cap_exceeded"


@then(parsers.parse("the run records show {aborted:d} aborted trial and {tot:d} total tokens"))
def run_records_aborted(output: Path, aborted: int, tot: int) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert sum(1 for c in summary["cells"] if c["status"] == "aborted") == aborted
    assert manifest["totals"]["aborted"] == aborted
    assert summary["usage"]["total_tokens"] == tot
    assert manifest["totals"]["usage"]["total_tokens"] == tot


# prototype-runs.feature — Digest-pinned caching reuses valid replies unless caching is disabled


@given(
    parsers.parse('a simulated model endpoint pinned to digest "{digest}" counting requests'),
    target_fixture="cache_probe",
)
def simulated_endpoint_counting(monkeypatch: pytest.MonkeyPatch, digest: str) -> dict:
    from experiment.adapters import _ollama_chat, backends

    state = {"calls": 0, "digest": digest}
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"

    def fake_chat(*_args, **_kwargs) -> dict:
        state["calls"] += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }

    monkeypatch.setattr(_ollama_chat, "chat_completions_sdk", fake_chat)
    monkeypatch.setattr(backends, "resolve_model_digest", lambda _session, _profile: digest)
    return state


@when(
    "I run two trials of the same cached condition and a third with caching bypassed",
    target_fixture="cache_runs",
)
def run_cached_cell_three_times(cli: CliRunner, output: Path, tmp_path: Path) -> list[dict]:
    cache_dir = tmp_path / "shared-llm-cache"
    runs_out: list[dict] = []
    for idx, extra in enumerate(("", "", " --no-cache"), start=1):
        out_dir = output.parent / f"cache-run-{idx}"
        res = run_cli(
            cli,
            f"run codegen --driver ollama --task analysis-de9im-001 "
            f"--cache-dir {cache_dir}{extra} --output-dir {out_dir}",
        )
        assert res["exit_code"] == 0, res["output"]
        runs_out.append(json.loads((out_dir / "summary.json").read_text(encoding="utf-8")))
    return runs_out


@then("the endpoint answered 2 requests with cache reuse false, true, false")
def verify_cache_reuse_sequence(cache_probe: dict, cache_runs: list[dict]) -> None:
    assert cache_probe["calls"] == 2
    assert [run["cells"][0]["cache_hit"] for run in cache_runs] == [False, True, False]


# workflow.feature — Timed-out commands fail whether their output is captured or passed through


@given("a preparation command that does not finish promptly", target_fixture="slow_command")
def slow_preparation_command() -> list[str]:
    return [sys.executable, "-c", "import time; time.sleep(5)"]


@when(
    "the workflow runs the command with a time limit in both output modes",
    target_fixture="timeouts",
)
def run_slow_command(slow_command: list[str]) -> list[str]:
    from experiment.adapters import subprocess_runner

    messages = []
    for run in (subprocess_runner.run_command, subprocess_runner.run_passthrough):
        with pytest.raises(subprocess_runner.CommandTimeoutError) as failure:
            run(slow_command, timeout=0.05)
        messages.append(str(failure.value))
    return messages


@then("both attempts report that the time limit expired")
def commands_timed_out(timeouts: list[str]) -> None:
    assert len(timeouts) == 2 and all("timed out" in message for message in timeouts)


# workflow.feature — Preparation commands retain their output and exit status


@given(
    parsers.parse("a preparation command that reports a message and exits with status {status:d}"),
    target_fixture="preparation_command",
)
def preparation_command_with_status(status: int) -> dict:
    return {"status": status, "message": "preparation complete"}


@when("the workflow runs the command in both output modes")
def run_preparation_command(preparation_command: dict, tmp_path: Path) -> None:
    from experiment.adapters import subprocess_runner

    status, message = preparation_command["status"], preparation_command["message"]
    command = [sys.executable, "-c", f"import sys; print({message!r}); sys.exit({status})"]
    preparation_command["captured"] = subprocess_runner.run_command(command, cwd=tmp_path)
    preparation_command["passed_through"] = subprocess_runner.run_passthrough(command, cwd=tmp_path)


@then("the captured message and both exit statuses are accurate")
def preparation_outcomes_match(preparation_command: dict) -> None:
    captured = preparation_command["captured"]
    assert captured.stdout.strip() == preparation_command["message"]
    assert captured.returncode == preparation_command["status"]
    assert preparation_command["passed_through"] == preparation_command["status"]


# workflow.feature — An unavailable tool version is reported honestly


@given("one available and one unavailable preparation tool", target_fixture="preparation_tools")
def available_and_unavailable_tools(tmp_path: Path) -> dict:
    return {"root": tmp_path}


@when("the researcher checks both tool versions")
def check_preparation_tool_versions(preparation_tools: dict) -> None:
    from experiment.adapters import subprocess_runner

    root = preparation_tools["root"]
    preparation_tools["available"] = subprocess_runner.soft_version(
        [sys.executable, "--version"], root
    )
    preparation_tools["missing"] = subprocess_runner.soft_version(
        ["nonexistent-binary-xyz-999"], root
    )


@then("the available tool reports its version and the missing tool is unavailable")
def preparation_tool_versions_are_honest(preparation_tools: dict) -> None:
    assert preparation_tools["available"].startswith("Python ")
    assert preparation_tools["missing"] == "unavailable"


# workflow.feature — Preflight validates the task suite and records environment details


@given("a workflow checkout with a pinned environment", target_fixture="preflight_workflow")
def valid_workflow_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    return setup_workflow_preflight(tmp_path, monkeypatch, invalid=False)


@when("the researcher performs workflow preflight")
def perform_workflow_preflight(cli: CliRunner, preflight_workflow: dict) -> None:
    preflight_workflow["result"] = run_cli(cli, "env preflight --run-id rid-1")


@then("the environment record identifies the checkout and dependency lock")
def preflight_records_environment(preflight_workflow: dict) -> None:
    assert preflight_workflow["result"]["exit_code"] == 0, preflight_workflow["result"]
    pins = (preflight_workflow["root"] / "results/rid-1/env-pins.txt").read_text(encoding="utf-8")
    assert "repo_sha=v1.0.0" in pins and "pixi_lock_sha256=" in pins


@then("the task suite was validated once")
def preflight_validated_once(preflight_workflow: dict) -> None:
    assert len(preflight_workflow["validated"]) == 1


# workflow.feature — Preflight rejects an invalid study instrument


@given("a workflow checkout with an invalid task suite", target_fixture="preflight_workflow")
def invalid_workflow_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    return setup_workflow_preflight(tmp_path, monkeypatch, invalid=True)


@then("the preflight explains why the task suite is invalid")
def preflight_invalid_explained(preflight_workflow: dict) -> None:
    result = preflight_workflow["result"]
    assert result["exit_code"] != 0 and "missing trap" in result["output"]


# workflow.feature — Model preparation records the model identity and test response


@given("a reachable model service for workflow preparation", target_fixture="workflow_model")
def available_workflow_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from experiment.adapters import ollama, subprocess_runner
    from experiment.services import workflow

    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(subprocess_runner, "which", lambda _name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama, "start_ollama", lambda *_a, **_kw: None)
    monkeypatch.setattr(ollama, "wait_ready", lambda *_a, **_kw: True)
    monkeypatch.setattr(ollama, "pull_model", lambda *_a, **_kw: 0)
    monkeypatch.setattr(ollama, "list_model_digest", lambda *_a, **_kw: "abcdef123456")
    monkeypatch.setattr(ollama, "smoke_generate", lambda _m, **_kw: {"response": "OK"})
    return tmp_path


@when("the researcher prepares the model for the workflow", target_fixture="result")
def prepare_model_for_workflow(cli: CliRunner, workflow_model: Path) -> dict:
    return run_cli(cli, "env model --model qwen2.5:3b --run-id rid-m")


@then("the model identity and test response are saved")
def model_preparation_saved(workflow_model: Path, result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    run_dir = workflow_model / "results/rid-m"
    assert (run_dir / "model-digest.txt").read_text(encoding="utf-8").strip() == (
        "qwen2.5:3b abcdef123456"
    )
    assert json.loads((run_dir / "model-smoke.json").read_text(encoding="utf-8")) == {
        "response": "OK"
    }


# workflow.feature — Pilot and smoke trials record their different outcomes


@given("a prepared model service and an isolated workflow", target_fixture="workflow_runtime")
def prepared_workflow_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from experiment.adapters import ollama, subprocess_runner
    from experiment.services import workflow

    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(subprocess_runner, "which", lambda _name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama, "start_ollama", lambda *_a, **_kw: None)
    monkeypatch.setattr(ollama, "list_model_digest", lambda *_a, **_kw: "sha256:abc123")
    monkeypatch.setattr(
        workflow.paths, "tasks_root", lambda _root=None: FEATURE_DIR.parent / "tasks"
    )
    seen = []

    def fake_run_cell(req):
        seen.append(req)
        (req.cell / "score.json").write_text('{"passed": true}', encoding="utf-8")
        return {
            "status": "ok",
            "oracle_passed": True,
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            "wall_s": 1.25,
            "error": None,
        }

    def fail_passthrough(cmd, **_kw):
        raise AssertionError(f"smoke probe must not spawn CLI subprocess: {cmd}")

    monkeypatch.setattr(workflow.workflow_pilot.runs_service, "run_cell", fake_run_cell)
    monkeypatch.setattr(subprocess_runner, "run_passthrough", fail_passthrough)
    return {"root": tmp_path, "seen": seen}


@when("the researcher runs a pilot trial and a smoke trial")
def run_pilot_and_smoke(cli: CliRunner, workflow_runtime: dict) -> None:
    workflow_runtime["pilot"] = run_cli(
        cli,
        "run trial --arm A --task-id analysis-de9im-001 --stage pilot "
        "--model qwen2.5:3b --run-id rid-p",
    )
    workflow_runtime["smoke"] = run_cli(
        cli, "run cell --arm B --task-id analysis-de9im-001 --stage smoke --run-id rid-s"
    )


@then("the pilot records the model identity and successful grading")
def pilot_identity_and_grade(workflow_runtime: dict) -> None:
    assert workflow_runtime["pilot"]["exit_code"] == 0, workflow_runtime["pilot"]
    assert len(workflow_runtime["seen"]) == 1
    assert workflow_runtime["seen"][0].model_digest == "sha256:abc123"
    cell = workflow_runtime["root"] / "results/rid-p/cell-A-analysis-de9im-001-r1"
    manifest = json.loads((cell / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "ok" and manifest["oracle_passed"] is True


@then("the smoke trial records a simulated check")
def smoke_cell_is_simulated(workflow_runtime: dict) -> None:
    assert workflow_runtime["smoke"]["exit_code"] == 0, workflow_runtime["smoke"]
    cell = workflow_runtime["root"] / "results/rid-s/cell-B-analysis-de9im-001-r1"
    manifest = json.loads((cell / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "mock-smoke"


# workflow.feature — Current run settings take precedence over older settings


@given("current and older workflow settings are both present", target_fixture="workflow_settings")
def mixed_workflow_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from experiment.services import workflow

    captured = []
    monkeypatch.setattr(
        workflow, "run_workflow_cell", lambda spec: (captured.append(spec), tmp_path)[1]
    )
    return {"captured": captured}


@when("the researcher starts a workflow trial with response reuse enabled")
def start_cell_with_reuse(cli: CliRunner, workflow_settings: dict) -> None:
    current = cli.invoke(
        app,
        ["run", "cell", "--task-id", "analysis-de9im-001", "--cache"],
        env={
            "EXPERIMENT_RUN_ID": "new-run-id",
            "RUN_ID": "legacy-run-id",
            "EXPERIMENT_MODEL": "new-model:7b",
            "MODEL": "legacy-model:3b",
        },
    )
    assert current.exit_code == 0, current.output
    workflow_settings["current"] = workflow_settings["captured"][-1]


@then("the trial uses the current settings and enables reuse")
def current_settings_are_used(workflow_settings: dict) -> None:
    spec = workflow_settings["current"]
    assert (spec.run_id, spec.model, spec.use_cache) == ("new-run-id", "new-model:7b", True)


@when("only older workflow settings are present")
def legacy_settings_are_supported(
    cli: CliRunner, workflow_settings: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXPERIMENT_RUN_ID", raising=False)
    monkeypatch.delenv("EXPERIMENT_MODEL", raising=False)
    result = cli.invoke(
        app,
        ["run", "cell", "--task-id", "analysis-de9im-001", "--use-cache"],
        env={"RUN_ID": "legacy-run-id", "MODEL": "legacy-model:3b"},
    )
    assert result.exit_code == 0, result.output
    spec = workflow_settings["captured"][-1]
    assert (spec.run_id, spec.model, spec.use_cache) == ("legacy-run-id", "legacy-model:3b", True)


@then("the trial uses the older settings and enables reuse")
def legacy_settings_are_used(workflow_settings: dict) -> None:
    spec = workflow_settings["captured"][-1]
    assert (spec.run_id, spec.model, spec.use_cache) == ("legacy-run-id", "legacy-model:3b", True)


# workflow.feature — Harvest records a failed determinism check for missing trial output


@given("a completed trial with no result to grade", target_fixture="empty_trial_harvest")
def completed_trial_without_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from experiment.adapters import subprocess_runner
    from experiment.services import workflow

    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)

    def fail_subprocess(cmd: list[str], **_kwargs: object) -> None:
        raise AssertionError(f"harvest must not spawn CLI subprocess: {cmd}")

    monkeypatch.setattr(subprocess_runner, "run_command", fail_subprocess)
    harvest = tmp_path / "harvest"
    cell = harvest / "experiment-A-analysis-de9im-001-rep1"
    cell.mkdir(parents=True)
    (cell / "manifest.json").write_text(
        json.dumps({"arm": "A", "task": "analysis-de9im-001", "rep": 1, "status": "ok"}),
        encoding="utf-8",
    )
    return harvest


@when("the researcher harvests the trial and checks determinism", target_fixture="empty_harvest")
def harvest_trial_without_result(empty_trial_harvest: Path) -> dict:
    from experiment.services import workflow

    summary = workflow.run_harvest(
        workflow.HarvestConfig(
            harvest_dir=empty_trial_harvest,
            arms=("A",),
            repetitions=1,
            fail_on_missing=False,
            skip_oracle=False,
            run_id="rid-det",
        )
    )
    return {"summary": summary, "harvest": empty_trial_harvest}


@then("the harvest reports a failed determinism check with its detailed report")
def failed_harvest_determinism(empty_harvest: dict) -> None:
    assert empty_harvest["summary"]["oracle"] == {"analysis-de9im-001/A/rep-1": "fail"}
    report = empty_harvest["harvest"] / "oracle" / "analysis-de9im-001-A-rep1.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["required_runs"] == 3
    assert payload["passed"] is False


# workflow.feature — Full scripted pass covers all pilot tasks across both paradigms


@when("I run a scripted pass over the full pilot suite in both paradigms", target_fixture="result")
def run_full_scripted_pass(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"run all --driver scripted --output-dir {output}")


@then("the run reports all six trials passed the oracle")
def run_reports_six(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    assert "6/6 trials oracle-passed" in result["output"], result["output"]


@then("every pilot task appears in both paradigms")
def every_task_in_both_paradigms(output: Path) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    seen = {(cell["task"], cell["arm"]) for cell in summary["cells"]}
    tasks = {task for task, _arm in seen}
    assert len(tasks) == 3, sorted(tasks)
    assert seen == {(task, arm) for task in tasks for arm in ("A", "B")}


@then("every trial saves a transcript and an oracle score")
def every_cell_saves_artifacts(output: Path) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["prototype"] is True
    for cell in summary["cells"]:
        rep = cell.get("repetition", 1)
        cell_dir = output / f"cell-{cell['arm']}-{cell['task']}-r{rep}"
        assert cell["prototype"] is True
        assert (cell_dir / "transcript.jsonl").is_file(), cell_dir
        if cell["task"] == "analysis-de9im-001":
            result = json.loads((cell_dir / "result.json").read_text(encoding="utf-8"))
            assert result["relation"] == "touches"
        score = json.loads((cell_dir / "score.json").read_text(encoding="utf-8"))
        assert score["meta"]["prototype"] is True
        assert score["checks"], cell_dir


# workflow.feature — Targeted scripted pass runs only the requested tasks


@when(
    parsers.parse('I run a scripted pass for tasks "{task_ids}" in both paradigms'),
    target_fixture="result",
)
def run_targeted_scripted_pass(cli: CliRunner, output: Path, task_ids: str) -> dict:
    return run_cli(cli, f"run all --driver scripted --task {task_ids} --output-dir {output}")


@then("the run reports all four trials passed the oracle")
def run_reports_four(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    assert "4/4 trials oracle-passed" in result["output"], result["output"]


@then(parsers.parse('the run omits task "{task_id}"'))
def run_omits_task(output: Path, task_id: str) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert {cell["task"] for cell in summary["cells"]} == {
        "prep-axis-order-001",
        "cartography-jenks-001",
    }
    assert task_id not in {cell["task"] for cell in summary["cells"]}


# workflow.feature — Outputs from a scripted run pass the three-pass determinism gate


@when(
    parsers.parse(
        'I verify determinism on that trial for task "{task_id}" in code-generation mode'
    ),
    target_fixture="result",
)
def verify_determinism_on_codegen_cell(
    cli: CliRunner, output: Path, suite: dict, task_id: str
) -> dict:
    cell = output / f"cell-B-{task_id}-r1"
    result = run_cli(
        cli, f"score determinism {task_id} --artifacts-dir {cell} --root {suite['path']}"
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    return {**result, "report": payload}


# workflow.feature — Completed multi-arm run packs into a verified run archive


@when("I pack and inspect the resulting run archive", target_fixture="result")
def pack_and_inspect_archive(cli: CliRunner, output: Path) -> dict:
    zip_path = output.parent / "packed-run.zip"
    packed = run_cli(
        cli,
        f"archive pack --harvest-dir {output} --output {zip_path} --no-harvest --run-id bdd-pack",
    )
    assert packed["exit_code"] == 0, packed["output"] + packed["stderr"] + packed["raised"]
    return run_cli(cli, f"archive inspect {zip_path}")


@then("the archive inspection reports six passed trials")
def archive_reports_six(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    assert "trials=6" in result["output"]
    assert "TSR=100.00%" in result["output"]


# workflow.feature — Task suite missing a required family is rejected


@given("a pilot task suite missing its cartography task", target_fixture="suite")
def suite_without_cartography(suite: dict) -> dict:
    (suite["root"] / "cartography-jenks-001.yaml").unlink()
    return suite


@then("the explanation names the missing task family")
def explanation_missing_family(result: dict) -> None:
    assert "missing task family C" in result["output"]


@then(parsers.parse('the explanation names the uncovered pilot trap "{trap}"'))
def explanation_uncovered_trap(result: dict, trap: str) -> None:
    assert "required pilot trap is not covered" in result["output"]
    assert trap in result["output"]


# workflow.feature — Task suite missing a required study trap is rejected


@given("a pilot task suite that no longer declares the axis-order trap", target_fixture="suite")
def suite_without_axis_trap(suite: dict) -> dict:
    task_path = suite["root"] / "prep-axis-order-001.yaml"
    task_path.write_text(
        task_path.read_text(encoding="utf-8").replace(
            "  - crs-axis-order\n", "  - topology-de9im\n"
        ),
        encoding="utf-8",
    )
    return suite


# workflow.feature — Task suite missing a referenced geographic fixture is rejected


@given("a pilot task suite missing its data-preparation fixture", target_fixture="suite")
def suite_without_fixture(suite: dict) -> dict:
    (suite["root"] / "fixtures/prepare/poland.geojson").unlink()
    return suite


@then("the explanation names the missing fixture")
def explanation_missing_fixture(result: dict) -> None:
    assert "fixture does not exist" in result["output"]
    assert "fixtures/prepare/poland.geojson" in result["output"]


# qgis-sandbox.feature — Availability check returns a definite verdict on the current machine


@when("I check whether the GIS script runtime is available", target_fixture="result")
def check_gis_runtime(cli: CliRunner) -> dict:
    return run_cli(cli, "env qgis check")


@then("the gate reports a definite availability verdict")
def gate_reports_verdict(result: dict) -> None:
    assert result["exit_code"] in {0, 3}, result["output"]
    available = "PyQGIS sandbox — available" in result["output"]
    unavailable = "PyQGIS unavailable" in result["output"]
    assert available != unavailable, result["output"]
    assert available == (result["exit_code"] == 0), result["output"]


@then("the exit status matches the availability verdict")
def exit_matches_verdict(result: dict) -> None:
    expected = 0 if "PyQGIS sandbox — available" in result["output"] else 3
    assert result["exit_code"] == expected, result["output"]


# qgis-sandbox.feature — Available GIS runtime reports its desktop and geospatial library versions


@given("an environment with a working GIS runtime")
def env_with_pyqgis(monkeypatch: pytest.MonkeyPatch) -> None:
    package = types.ModuleType("qgis")
    package.__path__ = []
    core = types.ModuleType("qgis.core")
    core.Qgis = types.SimpleNamespace(QGIS_VERSION=_PYQGIS_AVAILABLE["qgis"])
    core.GDAL_VERSION = _PYQGIS_AVAILABLE["gdal"]
    core.GEOS_VERSION = _PYQGIS_AVAILABLE["geos"]
    core.PROJ_VERSION = _PYQGIS_AVAILABLE["proj"]
    package.core = core
    monkeypatch.setitem(sys.modules, "qgis", package)
    monkeypatch.setitem(sys.modules, "qgis.core", core)


@then("the report lists the QGIS and geospatial library versions")
def report_lists_versions(result: dict) -> None:
    reported = " ".join(result["output"].split())
    for name, version in _PYQGIS_AVAILABLE.items():
        assert f"{name} {version}" in reported


# qgis-sandbox.feature — Unavailable GIS runtime explains how to install the sandbox environment


@then("the explanation names the sandbox environment to install")
def explanation_names_sandbox(result: dict) -> None:
    reported = result["output"] + result["stderr"] + result["raised"]
    assert "PyQGIS unavailable" in reported
    assert "PyQGIS is not importable from this interpreter." in reported
    assert "-e sandbox" in reported


# qgis-sandbox.feature — Missing script file is refused without creating an output folder


@given("a non-existent script path with a long directory name", target_fixture="script")
def missing_script_path(tmp_path: Path) -> Path:
    return _long_path(tmp_path, "nope.py")


@when("I execute that script in the isolated GIS runner", target_fixture="result")
def execute_gis_script(cli: CliRunner, script: Path, tmp_path: Path) -> dict:
    return run_cli(cli, f"env qgis run {script} --artifacts-dir {tmp_path / 'art'}")


@then("the explanation states that the script is missing")
def explanation_script_missing(result: dict, script: Path) -> None:
    assert f"missing script: {script}" in _unwrapped_output(result)


@then("no isolated artifacts folder is created")
def no_isolated_artifacts(tmp_path: Path) -> None:
    assert not (tmp_path / "art").exists()


# qgis-sandbox.feature — Running a script without the GIS runtime fails with setup guidance


@given(parsers.parse('a GIS script that prints "{text}"'), target_fixture="script")
def script_printing(tmp_path: Path, text: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GEOAI_TEST_SECRET", "must-not-reach-the-script")
    monkeypatch.setenv("PYTHONPATH", "/outside-the-sandbox")
    script = tmp_path / "ok.py"
    script.write_text(
        "import os, sys\n"
        f"print({text!r})\n"
        "print('ISOLATED=', sys.flags.isolated, sep='')\n"
        "print('QT=', os.environ.get('QT_QPA_PLATFORM'), sep='')\n"
        "print('SECRET_PRESENT=', 'GEOAI_TEST_SECRET' in os.environ, sep='')\n"
        "print('PYTHONPATH_PRESENT=', 'PYTHONPATH' in os.environ, sep='')\n"
        "print('HOME_IS_CWD=', os.path.samefile(os.environ['HOME'], os.getcwd()), sep='')\n",
        encoding="utf-8",
    )
    return script


@then("the isolated artifacts folder exists")
def isolated_artifacts_exists(tmp_path: Path) -> None:
    assert (tmp_path / "art").is_dir()


# qgis-sandbox.feature — Valid script runs inside the isolated artifacts folder and prints its
# output


@then("the script executes inside the isolated artifacts folder")
def script_executes_isolated(result: dict) -> None:
    for expected in (
        "ISOLATED=1",
        "QT=offscreen",
        "SECRET_PRESENT=False",
        "PYTHONPATH_PRESENT=False",
        "HOME_IS_CWD=True",
    ):
        assert expected in result["output"], result["output"]


# qgis-sandbox.feature — Failing script preserves its own non-zero exit status and error message


@given(parsers.parse("a GIS script that exits with status {code:d}"), target_fixture="script")
def script_exiting(tmp_path: Path, code: int) -> Path:
    script = tmp_path / "fail.py"
    script.write_text(
        f"import sys\nprint('out')\nprint('sandbox-error', file=sys.stderr)\nsys.exit({code})\n",
        encoding="utf-8",
    )
    return script


@then("the output shows the script error message")
def output_shows_error_message(result: dict) -> None:
    assert "sandbox-error" in result["output"]


# qgis-sandbox.feature — Runaway script is stopped when its time limit expires


@given("a GIS script that never finishes", target_fixture="script")
def script_hanging(tmp_path: Path) -> Path:
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    return script


@when(
    "I execute that script in the isolated GIS runner with a one-second limit",
    target_fixture="result",
)
def execute_gis_script_with_timeout(cli: CliRunner, script: Path, tmp_path: Path) -> dict:
    return run_cli(cli, f"env qgis run {script} --artifacts-dir {tmp_path / 'art'} --timeout 1")


@then("the explanation states that the script timed out")
def explanation_timed_out(result: dict) -> None:
    assert "timed out" in result["output"]


# Additional shared or compatibility steps


@then(parsers.parse('the catalogue names the "{op}" operation'))
def catalogue_names_op(result: dict, op: str) -> None:
    assert op in result["output"]
