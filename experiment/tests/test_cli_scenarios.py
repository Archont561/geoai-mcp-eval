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
from pathlib import Path

from cli_harness import check, write_cell, write_jenks_artifact
from cli_harness import write_point_artifact as _write_point
from cli_harness import write_relation_artifact as _write_relation
from pytest_bdd import given, parsers, scenarios, then, when
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


@when(parsers.parse('I run the command "{command}"'), target_fixture="result")
def i_run_the_command(
    cli: CliRunner, command: str, suite: dict, output: Path | None = None
) -> dict:
    # `{output}` is only present in the prototype scenarios; keep it empty elsewhere.
    substitutions = {"suite": suite["path"]}
    if output is not None:
        substitutions["output"] = str(output)
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


@then(parsers.parse('the output contains "{expected}"'))
def output_contains(result: dict, expected: str) -> None:
    assert expected in result["output"]


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
    assert "Task suite valid: 3 tasks" in result["stdout"]
    assert "pilot traps covered:" in result["stdout"]


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
    assert len(result["report"]["run_results"]) == 3


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
    for cell in summary["cells"]:
        cell_dir = output / cell["task"] / f"arm-{cell['arm']}"
        assert (cell_dir / "transcript.jsonl").is_file(), cell_dir
        assert (cell_dir / "score.json").is_file(), cell_dir


@then("the table has one row per cell of that run")
def table_has_row_per_cell(result: dict, output: Path) -> None:
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result["exit_code"] == 0, result["output"]
    assert len(result["rows"]) == len(summary["cells"])


@then("the output names the task family that is missing")
def output_names_missing_family(result: dict) -> None:
    assert "missing task family C" in result["output"]


@then("the output names the pilot trap that is uncovered")
def output_names_uncovered_trap(result: dict) -> None:
    assert "required pilot trap is not covered" in result["output"]
    assert "crs-axis-order" in result["output"]


@then("the output names the fixture that cannot be found")
def output_names_missing_fixture(result: dict) -> None:
    assert "fixture does not exist" in result["output"]
    assert "fixtures/prepare/poland.geojson" in result["output"]


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


@then("the output reports the size of the operation catalogue")
def output_reports_catalogue_size(result: dict) -> None:
    assert "14 ops" in result["output"]


@then('the output names the "relate_de9im" operation')
def output_names_operation(result: dict) -> None:
    assert "relate_de9im" in result["output"]


@then("the output reports the Poland–Czechia boundary relation")
def output_reports_relation(result: dict) -> None:
    assert "relate_de9im POL×CZE" in result["output"]
    assert "touches" in result["output"]


@then("the output says no cells were found")
def output_says_no_cells(result: dict) -> None:
    assert "no cells" in result["output"]


@then("the rescore reports that one of one cells passed the oracle")
def rescore_reports_one_of_one(rescored: dict) -> None:
    assert rescored["exit_code"] == 0, rescored["output"]
    assert "1/1 cells oracle-passed" in rescored["output"]


@then("showing the run prints its oracle scores")
def showing_prints_scores(cli: CliRunner, output: Path) -> None:
    shown = run_cli(cli, f"proto show {output}")
    assert shown["exit_code"] == 0, shown["output"]
    assert "Oracle scores" in shown["output"]


# --- bind the feature files --------------------------------------------------

for _feature in (
    "command-line.feature",
    "pilot-suite.feature",
    "analysis.feature",
    "prototype-runs.feature",
    "workflow.feature",
):
    scenarios(str(FEATURE_DIR / _feature))
