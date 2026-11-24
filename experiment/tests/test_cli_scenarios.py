"""Step definitions and scenario bindings for the experiment CLI's features.

The features live in ``experiment/features/``. Each ``scenarios`` call at the
bottom of this module binds one feature file, so a new scenario needs no Python
to be collected and run.

Steps and bindings share one module deliberately: pytest only parses a module's
fixtures when it collects that module, so a separate bindings module would be
collected before the steps existed and every scenario would fail with
``StepDefinitionNotFoundError``.
"""

from __future__ import annotations

import json
import shlex
import sys
import types
from pathlib import Path

import pytest
from cli_harness import check, write_cell, write_jenks_artifact
from cli_harness import write_point_artifact as _write_point
from cli_harness import write_relation_artifact as _write_relation
from pytest_bdd import given, parsers, scenarios, then, when
from rich.text import Text
from typer.testing import CliRunner

from experiment.cli._loader import app

FEATURE_DIR = Path(__file__).resolve().parents[1] / "features"


# --- running the whole application -------------------------------------------


class _Substitutions(dict):
    """Format mapping that leaves unknown `{placeholders}` alone.

    One generic step serves commands that take `{suite}` and commands that take
    `{output}`, so a placeholder a scenario does not use must stay literal
    rather than raise.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def run_cli(cli: CliRunner, command: str, **substitutions: str) -> dict:
    """Invoke the mounted application with a shell-like command line."""
    expanded = command.format_map(_Substitutions(substitutions))
    result = cli.invoke(app, shlex.split(expanded))
    # A command that raises (rather than exiting) reports on `exception`, so
    # scenarios can assert on the reason a failure gives, not only its code.
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
    """Check visible text rather than Rich's optional terminal styling."""
    return Text.from_ansi(result["output"].replace("\r\n", "\n")).plain


def _unwrapped_output(result: dict) -> str:
    """Remove console line wraps without inserting spaces into long paths."""
    return _plain_output(result).replace("\n", "")


def _long_path(parent: Path, leaf: str) -> Path:
    """Make path diagnostics wrap at the usual terminal width."""
    return parent / ("long-directory-name-for-wrapping-" * 4) / leaf


@when(parsers.parse('I run the command "{command}"'), target_fixture="result")
def i_run_the_command(
    cli: CliRunner, command: str, suite: dict, request: pytest.FixtureRequest
) -> dict:
    # pytest does not inject a fixture into an optional defaulted argument.
    # Resolve it only for scenarios whose command actually uses {output}.
    substitutions = {"suite": suite["path"]}
    if "{output}" in command:
        substitutions["output"] = str(request.getfixturevalue("output"))
    return run_cli(cli, command, **substitutions)


@when("I ask the command line for help", target_fixture="result")
def i_ask_for_help(cli: CliRunner) -> dict:
    return run_cli(cli, "--help")


@then(parsers.parse("the help names the {group} command group"))
def help_names_group(result: dict, group: str) -> None:
    assert group.strip('"') in result["output"]


@then("the command exits successfully")
def command_succeeds(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]


@then("the command fails")
def command_fails(result: dict) -> None:
    assert result["exit_code"] != 0, result["output"]


@then(parsers.parse("the command exits with code {code:d}"))
def command_exits_with_code(result: dict, code: int) -> None:
    assert result["exit_code"] == code, result["output"]


@given("a terminal that requests colored output")
def terminal_requests_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("NO_COLOR", raising=False)


@then(parsers.parse('the output contains "{expected}"'))
def output_contains(result: dict, expected: str) -> None:
    assert expected in _plain_output(result), result["output"]


@then("the output contains terminal styling")
def output_contains_terminal_styling(result: dict) -> None:
    assert "\x1b[" in result["output"], result["output"]


@then("the output names the assertions that have no predicate mapping")
def output_names_assertion(result: dict) -> None:
    reported = result["output"] + result["stderr"] + result["raised"]
    assert "assertions without predicate mapping" in reported
    assert "not-a-real-assertion" in reported


# --- pilot suite -------------------------------------------------------------


@given("a task suite copied without its schema", target_fixture="broken_suite")
def a_suite_without_schema(suite: dict) -> dict:
    (suite["root"] / "schema-v1.json").unlink()
    return suite


@then("the output reports that 3 tasks are valid and the pilot traps are covered")
def output_reports_valid_suite(result: dict) -> None:
    assert " ".join(result["stdout"].split()) == (
        "Task suite valid: 3 tasks; pilot traps covered: "
        "crs-axis-order, jenks-classification, topology-de9im"
    )


@then(parsers.parse("the output explains that the schema cannot be read"))
def output_explains_schema(result: dict) -> None:
    assert "cannot read schema" in result["stdout"]


@given(parsers.parse('no artefacts for task "{task_id}"'), target_fixture="artifacts")
def no_artefacts(tmp_path: Path, task_id: str) -> Path:
    return tmp_path / "missing"


@given(parsers.parse("artefacts that satisfy each pilot task"), target_fixture="artifacts")
def artefacts_satisfying_each_task(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    _write_point(root)
    _write_relation(root)
    write_jenks_artifact(root)
    return root


@when(
    parsers.parse('I check determinism for task "{task_id}"'),
    target_fixture="result",
)
def check_determinism(cli: CliRunner, artifacts: Path, suite: dict, task_id: str) -> dict:
    result = run_cli(
        cli,
        f"pilot determinism {task_id} --artifacts-dir {artifacts / task_id} --root {suite['path']}",
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    return {**result, "report": payload}


@then("the report says the task passed")
def report_passed(result: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    assert result["report"]["passed"] is True


@then("the report covers three runs")
def report_covers_three(result: dict) -> None:
    report = result["report"]
    assert report["required_runs"] == 3
    assert report["consistent"] is True
    assert [run["status"] for run in report["run_results"]] == ["passed"] * 3


@then("the report says the task failed")
def report_failed(result: dict) -> None:
    assert result["exit_code"] == 1, result["output"]
    assert result["report"]["passed"] is False


@then("the output says the task ID is unknown")
def output_says_unknown_task(result: dict) -> None:
    reported = result["output"] + result["stderr"] + result["raised"]
    assert "unknown task ID" in reported


# --- the workflow from suite check to predicate matrix -----------------------


@given("a task suite copied without its cartography task", target_fixture="suite")
def a_suite_without_cartography(suite: dict) -> dict:
    (suite["root"] / "cartography-jenks-001.yaml").unlink()
    return suite


@given("a task suite whose axis-order trap is no longer declared", target_fixture="suite")
def a_suite_without_axis_trap(suite: dict) -> dict:
    task_path = suite["root"] / "prep-axis-order-001.yaml"
    task_path.write_text(
        task_path.read_text(encoding="utf-8").replace(
            "  - crs-axis-order\n", "  - topology-de9im\n"
        ),
        encoding="utf-8",
    )
    return suite


@given("a task suite copied without its prepare fixture", target_fixture="suite")
def a_suite_without_fixture(suite: dict) -> dict:
    (suite["root"] / "fixtures/prepare/poland.geojson").unlink()
    return suite


@when(
    "I run a scripted prototype over the whole suite in both arms",
    target_fixture="result",
)
def run_whole_suite_both_arms(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"proto run --driver scripted --arm both --output-dir {output}")


@when(
    parsers.parse('I run a scripted prototype for the tasks "{task_ids}" in both arms'),
    target_fixture="result",
)
def run_task_subset_both_arms(cli: CliRunner, output: Path, task_ids: str) -> dict:
    return run_cli(
        cli,
        f"proto run --driver scripted --arm both --task {task_ids} --output-dir {output}",
    )


@when(
    parsers.parse(
        'I check determinism on the cell that run produced for task "{task_id}" in arm "{arm}"'
    ),
    target_fixture="result",
)
def check_determinism_on_cell(
    cli: CliRunner, output: Path, suite: dict, task_id: str, arm: str
) -> dict:
    cell = output / task_id / f"arm-{arm}"
    result = run_cli(
        cli, f"pilot determinism {task_id} --artifacts-dir {cell} --root {suite['path']}"
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    return {**result, "report": payload}


@when("I flatten that run against the shipped suite", target_fixture="result")
def flatten_that_run(cli: CliRunner, output: Path, suite: dict) -> dict:
    result = run_cli(cli, f"analyze flatten {output} --tasks {suite['path']}")
    result["rows"] = _table_rows(result["output"])
    return result


@then("the run reports that all six cells passed the oracle")
def run_reports_six_of_six(result: dict) -> None:
    # 3 pilot tasks x 2 arms: a pass here means the full matrix is scoreable.
    assert result["exit_code"] == 0, result["output"]
    assert "6/6 cells oracle-passed" in result["output"], result["output"]


@then("the run reports that all four cells passed the oracle")
def run_reports_four_of_four(result: dict) -> None:
    # 2 selected tasks x 2 arms: narrowing the run must not skip a cell.
    assert result["exit_code"] == 0, result["output"]
    assert "4/4 cells oracle-passed" in result["output"], result["output"]


@then("every pilot task appears in both arms")
def every_task_in_both_arms(output: Path) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    seen = {(cell["task"], cell["arm"]) for cell in summary["cells"]}
    tasks = {task for task, _arm in seen}
    assert len(tasks) == 3, sorted(tasks)
    assert seen == {(task, arm) for task in tasks for arm in ("A", "B")}


@then(parsers.parse('the run holds no cell for task "{task_id}"'))
def run_holds_no_cell(output: Path, task_id: str) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert {cell["task"] for cell in summary["cells"]} == {
        "prep-axis-order-001",
        "cartography-jenks-001",
    }, f"{task_id} must not be scored"


@then("every cell keeps a transcript and a score file")
def every_cell_keeps_artifacts(output: Path) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["prototype"] is True
    for cell in summary["cells"]:
        cell_dir = output / cell["task"] / f"arm-{cell['arm']}"
        assert cell["prototype"] is True
        assert (cell_dir / "transcript.jsonl").is_file(), cell_dir
        score = json.loads((cell_dir / "score.json").read_text(encoding="utf-8"))
        assert score["meta"]["prototype"] is True
        assert score["checks"], cell_dir


@then("the table has one row per cell of that run")
def table_has_row_per_cell(result: dict, output: Path) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result["exit_code"] == 0, result["output"]
    assert len(result["rows"]) == len(summary["cells"])


@then("the output names the task family that is missing")
def output_names_missing_family(result: dict) -> None:
    assert "missing task family C" in result["output"]


@then(parsers.parse('the output names the uncovered pilot trap "{trap}"'))
def output_names_uncovered_trap(result: dict, trap: str) -> None:
    assert "required pilot trap is not covered" in result["output"]
    assert trap in result["output"]


@then("the output names the fixture that cannot be found")
def output_names_missing_fixture(result: dict) -> None:
    assert "fixture does not exist" in result["output"]
    assert "fixtures/prepare/poland.geojson" in result["output"]


# --- the PyQGIS sandbox gate -------------------------------------------------
#
# PyQGIS is not consistently available in the test interpreter, so these
# scenarios replace only its imports. Version detection, command handling,
# subprocess plumbing, and output rendering all run as shipped.

_PYQGIS_AVAILABLE = {
    "qgis": "4.2",
    "gdal": "x",
    "geos": "y",
    "proj": "z",
    "python": sys.version.split()[0],
}


@given("a harness that cannot import PyQGIS")
def harness_without_pyqgis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "qgis", None)


@given("a working PyQGIS harness")
def harness_with_pyqgis(monkeypatch: pytest.MonkeyPatch) -> None:
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


@given("a long sandbox script path that does not exist", target_fixture="script")
def sandbox_script_missing(tmp_path: Path) -> Path:
    return _long_path(tmp_path, "nope.py")


@given(parsers.parse('a sandbox script that prints "{text}"'), target_fixture="script")
def sandbox_script_printing(tmp_path: Path, text: str, monkeypatch: pytest.MonkeyPatch) -> Path:
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


@given(parsers.parse("a sandbox script that exits with code {code:d}"), target_fixture="script")
def sandbox_script_exiting(tmp_path: Path, code: int) -> Path:
    script = tmp_path / "fail.py"
    script.write_text(
        f"import sys\nprint('out')\nprint('sandbox-error', file=sys.stderr)\nsys.exit({code})\n",
        encoding="utf-8",
    )
    return script


@given("a sandbox script that never finishes", target_fixture="script")
def sandbox_script_slow(tmp_path: Path) -> Path:
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    return script


@when("I ask the sandbox whether PyQGIS is available", target_fixture="result")
def ask_sandbox_availability(cli: CliRunner) -> dict:
    return run_cli(cli, "qgis check")


@when("I run that script in the sandbox", target_fixture="result")
def run_that_script(cli: CliRunner, script: Path, tmp_path: Path) -> dict:
    return run_cli(cli, f"qgis run {script} --artifacts-dir {tmp_path / 'art'}")


@when("I run that script in the sandbox with a one second timeout", target_fixture="result")
def run_that_script_with_timeout(cli: CliRunner, script: Path, tmp_path: Path) -> dict:
    return run_cli(cli, f"qgis run {script} --artifacts-dir {tmp_path / 'art'} --timeout 1")


@then("the sandbox reports a definite verdict")
def sandbox_reports_verdict(result: dict) -> None:
    # Either PyQGIS is there (0) or it is not (3); nothing in between is honest.
    # The panels' titles are the verdict, because "available" is a substring of
    # "PyQGIS unavailable" and would match both branches.
    assert result["exit_code"] in {0, 3}, result["output"]
    available = "PyQGIS sandbox — available" in result["output"]
    unavailable = "PyQGIS unavailable" in result["output"]
    assert available != unavailable, result["output"]
    assert available == (result["exit_code"] == 0), result["output"]


@then("the command exits with the verdict's code")
def command_exits_with_verdict(result: dict) -> None:
    expected = 0 if "PyQGIS sandbox — available" in result["output"] else 3
    assert result["exit_code"] == expected, result["output"]


@then("the output reports the QGIS and library versions")
def output_reports_qgis_versions(result: dict) -> None:
    reported = " ".join(result["output"].split())
    for name, version in _PYQGIS_AVAILABLE.items():
        assert f"{name} {version}" in reported


@then("the output names the sandbox environment to install")
def output_names_sandbox_env(result: dict) -> None:
    reported = result["output"] + result["stderr"] + result["raised"]
    assert "PyQGIS unavailable" in reported
    assert "PyQGIS is not importable from this interpreter." in reported
    assert "-e sandbox" in reported


@then("the output says the script is missing")
def output_says_script_missing(result: dict, script: Path) -> None:
    assert f"missing script: {script}" in _unwrapped_output(result)


@then("no sandbox artifacts directory is created")
def no_sandbox_artifacts_directory(tmp_path: Path) -> None:
    assert not (tmp_path / "art").exists()


@then("the sandbox artifacts directory exists")
def sandbox_artifacts_directory_exists(tmp_path: Path) -> None:
    assert (tmp_path / "art").is_dir()


@then("the script runs isolated in the artifacts directory")
def script_runs_isolated(result: dict) -> None:
    for expected in (
        "ISOLATED=1",
        "QT=offscreen",
        "SECRET_PRESENT=False",
        "PYTHONPATH_PRESENT=False",
        "HOME_IS_CWD=True",
    ):
        assert expected in result["output"], result["output"]


@then("the output shows the script's error output")
def output_shows_stderr(result: dict) -> None:
    assert "sandbox-error" in result["output"]


@then("the output says the script timed out")
def output_says_timed_out(result: dict) -> None:
    assert "timed out" in result["output"]


# --- analysis ----------------------------------------------------------------


@given("a results directory with scored runs", target_fixture="scored")
def results_with_runs(results: dict) -> dict:
    write_cell(
        results,
        "analysis-de9im-001",
        "A",
        [check("shared-boundary-relation", True)],
    )
    write_cell(
        results,
        "prep-axis-order-001",
        "B",
        [
            check("single-output-feature", True),
            check("representative-point-axis-order", True),
        ],
    )
    return results


@given("a run whose score file omits one predicate", target_fixture="scored")
def results_with_missing_predicate(results: dict) -> dict:
    write_cell(results, "analysis-de9im-001", "A", [check("shared-boundary-relation", True)])
    write_cell(results, "prep-axis-order-001", "B", [check("single-output-feature", False)])
    return results


@given("a run whose score file names an unknown assertion", target_fixture="scored")
def results_with_unknown_assertion(results: dict) -> dict:
    write_cell(results, "analysis-de9im-001", "A", [check("not-a-real-assertion", True)])
    return results


@given("a results directory with no score files", target_fixture="scored")
def empty_results(results: dict) -> dict:
    results["dir"].mkdir(parents=True, exist_ok=True)
    return results


@when("I flatten the results", target_fixture="result")
def flatten_results(cli: CliRunner, scored: dict) -> dict:
    result = run_cli(cli, f"analyze flatten {scored['dir']} --tasks {scored['tasks']}")
    result["rows"] = _table_rows(result["output"])
    return result


def _table_rows(output: str) -> list[list[str]]:
    """Parse the fixed-width table Typer prints into rows of cells."""
    lines = [line for line in output.splitlines() if line.strip()]
    rows = []
    for line in lines:
        cells = line.split()
        if cells and all(set(cell) <= {"0", "1"} for cell in cells[-2:]):
            rows.append(cells)
    return rows


@then("the table has one row per run")
def table_has_one_row_per_run(result: dict, scored: dict) -> None:
    assert result["exit_code"] == 0, result["output"]
    assert len(result["rows"]) == len(scored["cells"])


@then("every predicate column holds only 0 or 1")
def predicate_columns_are_binary(result: dict) -> None:
    assert result["rows"], "the table must have at least one row"
    for row in result["rows"]:
        assert {"0", "1"} >= set(row[-2:])


@then("that run's row stays in the table")
def row_stays(result: dict, scored: dict) -> None:
    assert len(result["rows"]) == len(scored["cells"])


@then("the missing predicate scores 0")
def missing_predicate_scores_zero(result: dict) -> None:
    assert result["rows"], "the table must have at least one row"
    assert "0" in result["rows"][0][-2:]


@then(parsers.parse("the output says no score files were found"))
def output_says_no_scores(result: dict) -> None:
    assert "no score.json files found" in result["output"]


# --- prototype runs ----------------------------------------------------------


@given("a prototype output directory", target_fixture="output")
def a_prototype_output_directory(tmp_path: Path) -> Path:
    return tmp_path / "out"


@given("a prototype output directory with a long path", target_fixture="output")
def a_long_prototype_output_directory(tmp_path: Path) -> Path:
    return _long_path(tmp_path, "out")


@given("the hosted backend has no API key")
def hosted_backend_has_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@then("no output directory is created")
def no_output_directory_created(output: Path) -> None:
    assert not output.exists()


@when(
    parsers.parse('I run a scripted prototype for task "{task_id}" in arm "{arm}"'),
    target_fixture="result",
)
def run_scripted_prototype(cli: CliRunner, output: Path, task_id: str, arm: str) -> dict:
    return run_cli(
        cli,
        f"proto run --driver scripted --arm {arm} --task {task_id} --output-dir {output}",
    )


@when("I rescore that run", target_fixture="rescored")
def rescore_that_run(cli: CliRunner, output: Path) -> dict:
    return run_cli(cli, f"proto score {output}")


@then("the run reports that one of one cells passed the oracle")
def run_reports_one_of_one(result: dict) -> None:
    assert "1/1 cells oracle-passed" in result["output"]


@then("the output directory holds a summary")
def output_holds_summary(output: Path) -> None:
    assert (output / "summary.json").is_file()


@then("the output warns that this is not a study result")
def output_warns_about_prototype(result: dict) -> None:
    assert "pipeline verification only, not a study result." in result["output"]


@then("the output reports the size of the operation catalogue")
def output_reports_catalogue_size(result: dict) -> None:
    assert "14 ops" in result["output"]


@then('the output names the "relate_de9im" operation')
def output_names_operation(result: dict) -> None:
    assert "relate_de9im" in result["output"]


@then("the output reports the tool count and the filtered Poland feature")
def output_reports_mcp_tools_and_filter(result: dict) -> None:
    for expected in ("list_tools", "14 tools", "filter_features POL", "1 feature", "Poland"):
        assert expected in result["output"], result["output"]


@then("the output reports the Poland–Czechia boundary relation")
def output_reports_relation(result: dict) -> None:
    assert "relate_de9im POL×CZE" in result["output"]
    assert "touches" in result["output"]


@then("the output says no cells were found")
def output_says_no_cells(result: dict, output: Path) -> None:
    assert f"no cells under {output}" in _unwrapped_output(result)


@then("the output says the summary is missing")
def output_says_summary_missing(result: dict, output: Path) -> None:
    assert f"missing {output / 'summary.json'}" in _unwrapped_output(result)


@then("the rescore reports that one of one cells passed the oracle")
def rescore_reports_one_of_one(rescored: dict) -> None:
    assert rescored["exit_code"] == 0, rescored["output"]
    assert "1/1 cells oracle-passed" in rescored["output"]


@then("showing the run prints its oracle scores")
def showing_prints_scores(cli: CliRunner, output: Path) -> None:
    shown = run_cli(cli, f"proto show {output}")
    assert shown["exit_code"] == 0, shown["output"]
    assert "Oracle scores" in shown["output"]


@when("I corrupt and rescore the result", target_fixture="rescored")
def corrupt_and_rescore(cli: CliRunner, output: Path) -> dict:
    path = output / "analysis-de9im-001" / "arm-B" / "result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result.update({"relation": "disjoint", "de9im": "FF*FF****"})
    path.write_text(json.dumps(result), encoding="utf-8")
    return run_cli(cli, f"proto score {output}")


@then("the rescore reports that no cells passed the oracle")
def rescore_reports_no_passes(rescored: dict) -> None:
    assert rescored["exit_code"] == 0, rescored["output"]
    assert "0/1 cells oracle-passed" in rescored["output"]
    assert "✗" in rescored["output"]


def _stub_arm_b_chat(monkeypatch: pytest.MonkeyPatch, usage: dict | None) -> None:
    import experiment.drivers as drivers

    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    payload: dict = {
        "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}]
    }
    if usage is not None:
        payload["usage"] = usage

    def fake_chat(*_args, **_kwargs) -> dict:
        return payload

    monkeypatch.setattr(drivers, "_chat_completions", fake_chat)


@given(parsers.parse("a stubbed Ollama endpoint reporting {inp:d} input and {out:d} output tokens"))
def stubbed_ollama_with_usage(monkeypatch: pytest.MonkeyPatch, inp: int, out: int) -> None:
    _stub_arm_b_chat(
        monkeypatch,
        {"prompt_tokens": inp, "completion_tokens": out, "total_tokens": inp + out},
    )


@given("a stubbed Ollama endpoint reporting no token usage")
def stubbed_ollama_without_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_arm_b_chat(monkeypatch, None)


def _read_transcript(output: Path) -> list[dict]:
    path = output / "analysis-de9im-001" / "arm-B" / "transcript.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@then(
    parsers.parse(
        "the cell transcript records {inp:d} input and {out:d} output tokens with no usage warning"
    )
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
        "summary.json and manifest.json record run token totals of "
        "{inp:d} input, {out:d} output, and {tot:d} total"
    )
)
def summary_and_manifest_record_totals(output: Path, inp: int, out: int, tot: int) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for usage in (summary["usage"], manifest["totals"]["usage"]):
        assert usage["input_tokens"] == inp
        assert usage["output_tokens"] == out
        assert usage["total_tokens"] == tot
        assert usage["cells_with_usage"] == 1
        assert usage["cells_missing_usage"] == 0


@then("the cell transcript records null usage with an explicit warning")
def transcript_records_null_usage_warning(output: Path) -> None:
    entries = _read_transcript(output)
    assistant = [e for e in entries if e.get("role") == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["usage"] is None
    warnings = [e for e in entries if e.get("event") == "usage_warning"]
    assert len(warnings) >= 1
    assert "did not report token usage" in warnings[0]["warning"]


@then(
    parsers.parse(
        "summary.json and manifest.json record null token totals with "
        "{missing:d} missing-usage cell"
    )
)
def summary_and_manifest_record_null_totals(output: Path, missing: int) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for usage in (summary["usage"], manifest["totals"]["usage"]):
        assert usage["input_tokens"] is None
        assert usage["output_tokens"] is None
        assert usage["total_tokens"] is None
        assert usage["cells_missing_usage"] == missing
        assert usage["warnings"]


@then("the cell is aborted for token_cap_exceeded without executing its code")
def cell_aborted_for_token_cap(output: Path) -> None:
    cell_dir = output / "analysis-de9im-001" / "arm-B"
    assert not (cell_dir / "result.json").exists()
    entries = _read_transcript(output)
    assert not any(e.get("role") == "tool_result" for e in entries)
    aborts = [e for e in entries if e.get("event") == "token_cap_exceeded"]
    assert len(aborts) == 1
    assert aborts[0]["reason"] == "token_cap_exceeded"
    score = json.loads((cell_dir / "score.json").read_text(encoding="utf-8"))
    assert score["meta"]["status"] == "aborted"
    assert score["meta"]["abort_reason"] == "token_cap_exceeded"


@then(
    parsers.parse(
        "summary.json and manifest.json record {aborted:d} aborted cell and {tot:d} total tokens"
    )
)
def summary_and_manifest_record_aborted(output: Path, aborted: int, tot: int) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert sum(1 for c in summary["cells"] if c["status"] == "aborted") == aborted
    assert manifest["totals"]["aborted"] == aborted
    assert summary["usage"]["total_tokens"] == tot
    assert manifest["totals"]["usage"]["total_tokens"] == tot


@given(
    parsers.parse('a stubbed Ollama endpoint with digest "{digest}" counting calls'),
    target_fixture="cache_probe",
)
def stubbed_ollama_counting_calls(monkeypatch: pytest.MonkeyPatch, digest: str) -> dict:
    import experiment.backends as backends
    import experiment.drivers as drivers

    state = {"calls": 0, "digest": digest}
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"

    def fake_chat(*_args, **_kwargs) -> dict:
        state["calls"] += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }

    monkeypatch.setattr(drivers, "_chat_completions", fake_chat)
    monkeypatch.setattr(backends, "resolve_model_digest", lambda _session, _profile: digest)
    return state


@when(
    "I run a cached prototype cell twice and a third time with --no-cache",
    target_fixture="cache_runs",
)
def run_cached_cell_three_times(cli: CliRunner, output: Path, tmp_path: Path) -> list[dict]:
    cache_dir = tmp_path / "shared-llm-cache"
    runs_out: list[dict] = []
    for idx, extra in enumerate(("", "", " --no-cache"), start=1):
        out_dir = output.parent / f"cache-run-{idx}"
        res = run_cli(
            cli,
            f"proto run --driver ollama --task analysis-de9im-001 --arm B "
            f"--cache-dir {cache_dir}{extra} --output-dir {out_dir}",
        )
        assert res["exit_code"] == 0, res["output"]
        runs_out.append(json.loads((out_dir / "summary.json").read_text(encoding="utf-8")))
    return runs_out


@then("the endpoint was called 2 times with cache_hit false, true, false in summaries")
def verify_cache_hit_sequence(cache_probe: dict, cache_runs: list[dict]) -> None:
    assert cache_probe["calls"] == 2
    hits = [run["cells"][0]["cache_hit"] for run in cache_runs]
    assert hits == [False, True, False]


# --- bind the feature files --------------------------------------------------

for _feature in (
    "command-line.feature",
    "pilot-suite.feature",
    "analysis.feature",
    "prototype-runs.feature",
    "workflow.feature",
    "qgis-sandbox.feature",
):
    scenarios(str(FEATURE_DIR / _feature))
