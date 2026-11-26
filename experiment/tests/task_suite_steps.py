"""Scenarios for diagnostics on damaged pilot task suites."""

import json
from pathlib import Path

import yaml
from pytest_bdd import given, parsers, then, when

from experiment.adapters.task_suite import validate_suite


def _damage_group_0(suite: Path, path: Path, task: dict, problem: str) -> tuple:
    expected = []
    save = True
    if problem == "duplicate tasks and an unsupported check":
        path = suite / "analysis-de9im-001.yaml"
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        task["id"] = "prep-axis-order-001"
        task["oracle"]["assertions"][0]["type"] = "not-implemented"
        expected = ["prep-axis-order-001.yaml", "duplicate task ID", "unimplemented type"]
    if problem == "a missing title and an unsafe fixture":
        del task["title"]
        task["fixtures"]["input"] = "../../outside.geojson"
        expected = ["'title' is a required property", "escapes the task-suite directory"]
    elif problem in {"an unreadable validation schema", "an invalid validation schema"}:
        schema = suite / "schema-v1.json"
        schema.write_text(
            "{not json" if problem.startswith("an unreadable") else json.dumps({"type": 5}),
            encoding="utf-8",
        )
        expected, save = ["invalid JSON schema"], False
    elif problem == "no task definitions":
        for item in suite.glob("*.yaml"):
            item.unlink()
        expected, save = ["no task YAML files found"], False
    elif problem == "a task definition that is not a record":
        for item in suite.glob("*.yaml"):
            item.unlink()
        path.write_text("- not\n- a mapping\n", encoding="utf-8")
        expected, save = ["task document must be a YAML mapping"], False
    return path, task, expected, save


def _damage_group_1(suite: Path, path: Path, task: dict, problem: str) -> tuple:
    expected = []
    save = True
    if problem == "an invalid fixture and missing baseline":
        task["human_baseline"]["status"] = "complete"
        task["human_baseline"]["artifact_dir"] = "baselines/missing"
        (suite / task["fixtures"]["input"]).write_text(
            json.dumps({"type": "FeatureCollection", "features": "bad"}), encoding="utf-8"
        )
        expected = [
            "completed human baseline artifact_dir does not exist",
            "fixture is not a GeoJSON FeatureCollection",
        ]
    elif problem in {"malformed feature properties", "a fixture that is not a feature collection"}:
        fixture = suite / task["fixtures"]["input"]
        payload = (
            {"type": "FeatureCollection", "features": [{"properties": []}]}
            if problem.startswith("malformed")
            else {"type": "Feature", "features": []}
        )
        fixture.write_text(json.dumps(payload), encoding="utf-8")
        expected = [
            "cannot read fixture"
            if problem.startswith("malformed")
            else "not a GeoJSON FeatureCollection"
        ]
    return path, task, expected, save


def _damage_group_2(suite: Path, path: Path, task: dict, problem: str) -> tuple:
    expected = []
    save = True
    if problem == "an unsafe result path and incomplete check":
        check = task["oracle"]["assertions"][1]
        del check["id_field"]
        check["output"] = "../../outside.json"
        expected = ["missing 'id_field'", "unsafe output path"]
    elif problem == "an invalid grading section":
        task["oracle"] = []
        expected = ["is not of type 'object'"]
    elif problem == "an unsupported spatial relation":
        task["oracle"] = {
            "determinism_runs": 3,
            "assertions": [
                {
                    "id": "bad",
                    "type": "de9im_relation",
                    "expected_relation": "crosses",
                    "output": "out.json",
                }
            ],
        }
        expected = ["unsupported relation name", "missing 'fixture'"]
    elif problem == "an unreadable task definition":
        path.write_text("id: [broken\n", encoding="utf-8")
        expected, save = ["cannot parse YAML"], False
    elif problem == "incorrectly shaped task details":
        task["fixtures"] = []
        task["oracle"]["assertions"] = 5
        task["required_traps"] = [[]]
        task["family"] = []
        expected = ["is not of type"]
    elif problem == "a schema that is not a record":
        (suite / "schema-v1.json").write_text("[]", encoding="utf-8")
        expected, save = ["schema root must be an object"], False
    return path, task, expected, save


@given(parsers.parse("a pilot suite damaged by {problem}"), target_fixture="damaged_suite")
def damage_pilot_suite(copied_task_suite: Path, problem: str) -> dict:
    suite = copied_task_suite
    path = suite / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    for handler in (_damage_group_0, _damage_group_1, _damage_group_2):
        path, task, expected, save = handler(suite, path, task, problem)
        if expected:
            break
    else:
        raise AssertionError(f"unknown suite problem: {problem}")
    if save:
        path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
    return {"suite": suite, "expected": expected, "problem": problem}


@when("the researcher checks the damaged suite")
def check_damaged_suite(damaged_suite: dict) -> None:
    damaged_suite["report"] = validate_suite(damaged_suite["suite"])


@then("the report explains the task suite problems")
def explain_suite_problems(damaged_suite: dict) -> None:
    report = damaged_suite["report"]
    assert not report.passed
    messages = "\n".join(str(issue) for issue in report.issues)
    for expected in damaged_suite["expected"]:
        assert expected in messages
    schema_problems = {"an unreadable validation schema", "an invalid validation schema"}
    if damaged_suite["problem"] in schema_problems:
        assert report.task_count == 0


@given("a task collection with one valid and one unreadable task", target_fixture="lookup_suite")
def task_collection_with_unreadable_sibling(tmp_path: Path, sample_task_document: dict) -> dict:
    valid = tmp_path / "zzz-valid.yaml"
    broken = tmp_path / "aaa-broken.yaml"
    valid.write_text(
        yaml.safe_dump({**sample_task_document, "id": "lookup-task"}), encoding="utf-8"
    )
    broken.write_text("id: [unclosed\n", encoding="utf-8")
    return {"root": tmp_path, "valid": valid, "broken": broken}


@when("the researcher looks up the valid task")
def look_up_intact_task(lookup_suite: dict) -> None:
    from experiment.adapters.task_repository import discover_task_files, find_task, find_task_file

    root = lookup_suite["root"]
    lookup_suite["path"] = find_task_file(root, "lookup-task")
    lookup_suite["task"] = find_task(root, "lookup-task")
    lookup_suite["discovered"] = discover_task_files(root)


@then("the valid task is found and its details are available")
def intact_task_found(lookup_suite: dict) -> None:
    assert lookup_suite["path"] == lookup_suite["valid"]
    assert lookup_suite["task"].id == "lookup-task"


@then("both task documents are discoverable")
def both_task_documents_discovered(lookup_suite: dict) -> None:
    assert lookup_suite["discovered"] == [lookup_suite["broken"], lookup_suite["valid"]]


@when("the researcher loads the entire task collection")
def load_complete_collection(lookup_suite: dict) -> None:
    import pytest

    from experiment.adapters.task_repository import TaskLoadError, load_suite

    with pytest.raises(TaskLoadError) as error:
        load_suite(lookup_suite["root"])
    lookup_suite["error"] = error.value


@then("the unreadable task is identified as the loading failure")
def unreadable_task_identified(lookup_suite: dict) -> None:
    assert lookup_suite["error"].path == lookup_suite["broken"]


@when("the researcher looks up a task that is not present")
def look_up_absent_task(lookup_suite: dict) -> None:
    import pytest

    from experiment.adapters.task_repository import TaskNotFoundError, find_task_file

    with pytest.raises(TaskNotFoundError) as error:
        find_task_file(lookup_suite["root"], "missing-task")
    lookup_suite["error"] = error.value


@then("the missing-task report identifies the task and collection")
def missing_task_identified(lookup_suite: dict) -> None:
    error = lookup_suite["error"]
    assert isinstance(error, LookupError)
    assert error.task_id == "missing-task"
    assert error.suite == lookup_suite["root"]
    assert "unknown task ID: missing-task" in str(error)


@given("the published pilot tasks", target_fixture="pilot_result_files")
def published_pilot_tasks(pilot_task_paths: dict[str, Path]) -> dict:
    return {"paths": pilot_task_paths.values()}


@when("the researcher prepares their expected result files")
def prepare_pilot_result_names(pilot_result_files: dict) -> None:
    from experiment.adapters import harness_io, task_repository

    pilot_result_files["names"] = {
        (task := task_repository.load_task(path)).id: harness_io.deliverable_name(task)
        for path in pilot_result_files["paths"]
    }


@then("the representative-point task expects geographic output")
def point_task_result_is_geographic(pilot_result_files: dict) -> None:
    assert pilot_result_files["names"]["prep-axis-order-001"] == "result.geojson"


@then("the other pilot tasks expect ordinary structured results")
def other_task_results_are_structured(pilot_result_files: dict) -> None:
    other = {
        key: value
        for key, value in pilot_result_files["names"].items()
        if key != "prep-axis-order-001"
    }
    assert other
    assert all(value == "result.json" for value in other.values())
