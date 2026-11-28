"""Researcher-facing specifications for oracle determinism."""

from pathlib import Path

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from experiment.oracle import AssertionResult, OracleVerdict, run_determinism_gate

ROOT = Path(__file__).resolve().parents[3]
scenarios(str(ROOT / "experiment" / "features" / "oracle-grading.feature"))


@pytest.fixture
def verdicts() -> tuple[OracleVerdict, OracleVerdict]:
    passed = OracleVerdict(
        passed=True, checks=(AssertionResult(assertion_id="check", passed=True, message="pass"),)
    )
    failed = OracleVerdict(
        passed=False, checks=(AssertionResult(assertion_id="check", passed=False, message="fail"),)
    )
    return passed, failed


def _change_output(path: Path, change) -> None:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def _boundary_trial(tmp_path: Path, *, valid: bool) -> dict:
    import json

    directory = tmp_path / "boundary"
    directory.mkdir()
    output = (
        {"relation": "touches", "de9im": "FF2F11212"}
        if valid
        else {"relation": "disjoint", "de9im": "FF2FF1212"}
    )
    (directory / "result.json").write_text(json.dumps(output), encoding="utf-8")
    return {"task": "analysis-de9im-001", "path": directory, "valid": valid}


# Step definitions follow feature and scenario order; shared steps appear at first use.

# oracle-grading.feature — Repeated checks disagree


@given("a pilot task with conflicting grading verdicts", target_fixture="grading")
def conflicting_verdicts(pilot_task_paths: dict[str, Path], verdicts: tuple, mocker) -> dict:
    passed, failed = verdicts
    return {
        "path": pilot_task_paths["prep-axis-order-001"],
        "evaluator": mocker.Mock(side_effect=[passed, failed, passed]),
    }


@when("the researcher checks grading determinism", target_fixture="report")
def check_determinism(tmp_path: Path, grading: dict):
    if grading["evaluator"] is None:
        return run_determinism_gate(grading["path"], tmp_path)
    return run_determinism_gate(grading["path"], tmp_path, grading["evaluator"])


@then("the determinism check fails because its verdicts are inconsistent")
def verdicts_inconsistent(report) -> None:
    assert not report.passed
    assert not report.consistent


# oracle-grading.feature — A repeated check does not return a verdict


@given("a pilot task with a missing grading verdict", target_fixture="grading")
def missing_verdict(pilot_task_paths: dict[str, Path], verdicts: tuple, mocker) -> dict:
    passed, _ = verdicts
    return {
        "path": pilot_task_paths["prep-axis-order-001"],
        "evaluator": mocker.Mock(side_effect=[passed, None, passed]),
    }


@then("the report identifies the missing verdict")
def missing_verdict_reported(report) -> None:
    assert any("missing" in issue for issue in report.issues)


# oracle-grading.feature — An unreadable task cannot be checked for determinism


@given("a task document that cannot be read", target_fixture="grading")
def unreadable_task(tmp_path: Path) -> dict:
    path = tmp_path / "broken.yaml"
    path.write_text("id: [unclosed\n", encoding="utf-8")
    return {"path": path, "evaluator": None}


@then("the determinism report explains that the task could not be loaded")
def unloadable_task_reported(report) -> None:
    assert not report.passed
    assert any(issue.startswith("task could not be loaded: ") for issue in report.issues)


# oracle-grading.feature — A grading check fails unexpectedly


@given("a pilot task with an unavailable grading check", target_fixture="grading")
def unavailable_grader(pilot_task_paths: dict[str, Path], mocker) -> dict:
    return {
        "path": pilot_task_paths["prep-axis-order-001"],
        "evaluator": mocker.Mock(side_effect=RuntimeError("simulated oracle failure")),
    }


@then("the determinism check fails and explains the grading error")
def grading_error_reported(report) -> None:
    assert not report.passed
    assert any("simulated oracle failure" in issue for issue in report.issues)


# oracle-grading.feature — A task requests fewer than the required three checks


@given("a pilot task configured for only two grading checks", target_fixture="grading")
def task_with_two_checks(tmp_path: Path, pilot_task_paths: dict[str, Path]) -> dict:
    source = pilot_task_paths["prep-axis-order-001"]
    task = yaml.safe_load(source.read_text(encoding="utf-8"))
    task["oracle"]["determinism_runs"] = 2
    path = tmp_path / "bad-runs.yaml"
    path.write_text(yaml.safe_dump(task), encoding="utf-8")
    return {"path": path, "evaluator": None}


@then("the determinism check fails and states that three checks are required")
def required_checks_reported(report) -> None:
    assert not report.passed
    assert any("exactly 3" in issue for issue in report.issues)


# oracle-grading.feature — A reversed point is recorded as a silent invalid result


@given("a completed trial with a reversed representative point", target_fixture="trial_measurement")
def reversed_trial(tmp_path: Path) -> dict:
    import json

    directory = tmp_path / "silent"
    directory.mkdir()
    feature = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"ADMIN": "Poland", "ISO_A3": "POL"},
                "geometry": {"type": "Point", "coordinates": [52.0, 19.0]},
            }
        ],
    }
    (directory / "result.geojson").write_text(json.dumps(feature), encoding="utf-8")
    (directory / "transcript.jsonl").write_text(
        json.dumps({"role": "assistant", "content": "```python\nprint(1)\n```"})
        + "\n"
        + json.dumps({"role": "tool_result", "returncode": 0, "stdout": "{}"})
        + "\n",
        encoding="utf-8",
    )
    return {"task": "prep-axis-order-001", "path": directory}


@when("the researcher measures that trial")
def measure_trial_evidence(trial_measurement: dict) -> None:
    from experiment.domain.run import TokenUsage, TrialKey
    from experiment.services.measurement import TrialMeasurementOptions, measure_trial

    task = trial_measurement["task"]
    task_path = ROOT / "experiment" / "tasks" / f"{task}.yaml"
    is_boundary = task == "analysis-de9im-001"
    key = TrialKey(
        task_id=task,
        paradigm="typed_mcp" if is_boundary else "codegen",
        enforcement_level="semantic_repair" if is_boundary else "none",
        repetition=1,
    )
    options = TrialMeasurementOptions(wall_seconds=2.5)
    if trial_measurement.get("valid"):
        report = run_determinism_gate(task_path, trial_measurement["path"])
        trial_measurement["audit"] = report
        options = TrialMeasurementOptions(
            wall_seconds=1.2,
            token_usage=TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70),
            determinism=report,
        )
    trial_measurement["result"] = measure_trial(
        task_path, trial_measurement["path"], key=key, options=options
    )


@then("the measurement records a silent spatial failure and a partial score")
def measured_silent_spatial_failure(trial_measurement: dict) -> None:
    result = trial_measurement["result"]
    assert not result.outcomes.task_success
    assert result.outcomes.predicate_score == pytest.approx(0.5)
    assert result.outcomes.silent_invalid is True
    checks = {item.assertion_id: item for item in result.assertions}
    assert checks["single-output-feature"].tier == "trivial"
    assert checks["single-output-feature"].predicate == "feature_count"
    assert checks["single-output-feature"].passed is True
    assert checks["representative-point-axis-order"].tier == "spatial"
    assert checks["representative-point-axis-order"].predicate == "point_axis_order"
    assert checks["representative-point-axis-order"].passed is False


# oracle-grading.feature — A missing result is not a silent invalid result


@given("a trial with no geographic result", target_fixture="trial_measurement")
def trial_without_result(tmp_path: Path) -> dict:
    directory = tmp_path / "empty"
    directory.mkdir()
    return {"task": "prep-axis-order-001", "path": directory}


@then("the measurement records failure without silent invalidity")
def measured_missing_output(trial_measurement: dict) -> None:
    outcomes = trial_measurement["result"].outcomes
    assert outcomes.task_success is False and outcomes.predicate_score == 0.0
    assert outcomes.silent_invalid is False


# oracle-grading.feature — An incorrect boundary relation is silently invalid


@given("a completed trial with an incorrect boundary relation", target_fixture="trial_measurement")
def incorrect_boundary_trial(tmp_path: Path) -> dict:
    return _boundary_trial(tmp_path, valid=False)


@then("the measurement records a silent invalid boundary result")
def measured_bad_boundary(trial_measurement: dict) -> None:
    outcomes = trial_measurement["result"].outcomes
    assert outcomes.task_success is False and outcomes.silent_invalid is True


# oracle-grading.feature — A valid boundary trial preserves grading, determinism, and usage


@given(
    "a valid boundary trial with recorded usage and determinism checks",
    target_fixture="trial_measurement",
)
def valid_boundary_trial(tmp_path: Path) -> dict:
    return _boundary_trial(tmp_path, valid=True)


@then("the measurement records successful grading and the audit and usage")
def measured_success_and_audit(trial_measurement: dict) -> None:
    from experiment.domain.run import DeterminismAudit
    from experiment.services.measurement import determinism_report_to_audit

    result = trial_measurement["result"]
    assert result.outcomes.task_success is True and result.outcomes.predicate_score == 1.0
    assert result.outcomes.silent_invalid is False
    audit = determinism_report_to_audit(trial_measurement["audit"])
    assert audit == DeterminismAudit(
        passes_required=3, passes_executed=3, consistent=True, passed=True, issues=[]
    )
    assert result.determinism == audit and result.economics.tokens.total_tokens == 70


# oracle-grading.feature — A verified human reference contributes to trial measurements


@given(
    "a completed human reference with a valid boundary result", target_fixture="human_measurement"
)
def human_reference_evidence(tmp_path: Path) -> dict:
    trial = _boundary_trial(tmp_path, valid=True)
    record = {
        "record_version": 2,
        "status": "complete",
        "task_id": "analysis-de9im-001",
        "participant_code": "H-01",
        "session": {
            "elapsed_minutes": 4.5,
            "steps": 5,
            "tools": ["native:extractbyattribute", "qgis:topologicalrelations"],
        },
        "study_metrics": {"status": "complete", "processing_step_count": 2, "manual_step_count": 3},
        "oracle_passed": True,
    }
    return {"record": record, "path": trial["path"]}


@when("the researcher measures the human reference")
def measure_human_reference_evidence(human_measurement: dict) -> None:
    from experiment.services.measurement import measure_human_reference

    human_measurement["result"] = measure_human_reference(
        human_measurement["record"],
        task_path=ROOT / "experiment/tasks/analysis-de9im-001.yaml",
        artifacts_dir=human_measurement["path"],
        repetition=1,
    )
    human_measurement["record_only"] = measure_human_reference(
        human_measurement["record"], repetition=2
    )


@then("the measurement records the successful result and participant effort")
def human_effort_measured(human_measurement: dict) -> None:
    result = human_measurement["result"]
    assert result.key.paradigm == "human_gui" and result.key.enforcement_level == "none"
    assert result.key.task_id == "analysis-de9im-001"
    assert result.outcomes.task_success is True and result.outcomes.predicate_score == 1.0
    assert result.economics.wall_seconds == pytest.approx(270.0)
    assert result.economics.human_steps == 5 and result.economics.tool_calls == 2
    assert result.economics.tokens.total_tokens is None


@then("the recorded result can also be measured without the output files")
def human_record_only_is_measured(human_measurement: dict) -> None:
    from experiment.domain.run import AssertionResult

    result = human_measurement["record_only"]
    assert result.key.repetition == 2 and result.outcomes.task_success is True
    assert result.assertions == [
        AssertionResult(assertion_id="recorded-oracle", passed=True, detail="from record")
    ]


# oracle-grading.feature — Correct pilot results pass grading


@given(parsers.parse("the reference output for the {task} pilot task"), target_fixture="output")
def reference_output(task: str, expected_artifacts_dir: Path, pilot_task_paths: dict[str, Path]):
    task_id = {
        "representative point": "prep-axis-order-001",
        "boundary relation": "analysis-de9im-001",
        "natural breaks": "cartography-jenks-001",
    }[task]
    return {"task": pilot_task_paths[task_id], "directory": expected_artifacts_dir / task_id}


@when("the researcher grades the output", target_fixture="verdict")
def grade_output(output: dict):
    from experiment.oracle import evaluate_task

    return evaluate_task(output["task"], output["directory"])


@then("the output passes grading")
def output_passes(verdict) -> None:
    assert verdict.passed, verdict.to_dict()


# oracle-grading.feature — Reversed coordinates are rejected


@given("a representative point with longitude and latitude reversed", target_fixture="output")
def swapped_coordinates(expected_artifacts_dir: Path, pilot_task_paths: dict[str, Path]) -> dict:
    output = reference_output("representative point", expected_artifacts_dir, pilot_task_paths)

    def swap(value):
        geometry = value["features"][0]["geometry"]
        geometry["coordinates"] = geometry["coordinates"][::-1]

    _change_output(output["directory"] / "result.geojson", swap)
    return output


@then("the output fails grading with an axis-order explanation")
def axis_order_fails(verdict) -> None:
    assert not verdict.passed
    assert any("expected lon/lat" in check.message for check in verdict.checks)


# oracle-grading.feature — An incorrect boundary relation is rejected


@given("a boundary relation with an incorrect intersection pattern", target_fixture="output")
def wrong_relation(expected_artifacts_dir: Path, pilot_task_paths: dict[str, Path]) -> dict:
    output = reference_output("boundary relation", expected_artifacts_dir, pilot_task_paths)
    _change_output(
        output["directory"] / "result.json", lambda value: value.update(de9im="FFFFFFFFF")
    )
    return output


@then("the output fails grading")
def output_fails(verdict) -> None:
    assert not verdict.passed


# oracle-grading.feature — An incorrect natural-breaks class is rejected


@given("a natural-breaks result with an incorrect class assignment", target_fixture="output")
def wrong_class(expected_artifacts_dir: Path, pilot_task_paths: dict[str, Path]) -> dict:
    output = reference_output("natural breaks", expected_artifacts_dir, pilot_task_paths)
    _change_output(
        output["directory"] / "result.json", lambda value: value["assignments"].update(USA=4)
    )
    return output


# oracle-grading.feature — A malformed representative point is rejected


@given(parsers.parse("a representative-point output exhibiting {problem}"), target_fixture="output")
def malformed_point(
    problem: str, expected_artifacts_dir: Path, pilot_task_paths: dict[str, Path]
) -> dict:
    output = reference_output("representative point", expected_artifacts_dir, pilot_task_paths)

    def modify(value):
        feature = value["features"][0]
        if problem == "the wrong country code":
            feature["properties"] = {"ADMIN": "Poland", "ISO_A3": "CZE"}
        elif problem == "a non-point geometry":
            feature["geometry"] = {"type": "LineString", "coordinates": []}
        elif problem == "incomplete coordinates":
            feature["geometry"] = {"type": "Point", "coordinates": [1]}
        else:
            raise ValueError(f"Unknown problem: {problem}")

    _change_output(output["directory"] / "result.geojson", modify)
    return output


@then(parsers.parse("the grading report explains the {problem}"))
def malformed_point_explained(verdict, problem: str) -> None:
    expected = {
        "the wrong country code": "must preserve ISO_A3='POL'",
        "a non-point geometry": "must be a GeoJSON Point",
        "incomplete coordinates": "[longitude, latitude]",
    }[problem]
    assert not verdict.passed
    assert expected in verdict.checks[1].message


# oracle-grading.feature — Unrequested information in an output is rejected


@given(parsers.parse("the {task} result contains an unrequested field"), target_fixture="output")
def output_with_extra_field(
    task: str, expected_artifacts_dir: Path, pilot_task_paths: dict[str, Path]
) -> dict:
    output = reference_output(task, expected_artifacts_dir, pilot_task_paths)
    field = {"boundary relation": "explanation", "natural breaks": "notes"}[task]
    _change_output(
        output["directory"] / "result.json", lambda value: value.update({field: "unexpected"})
    )
    return output


# oracle-grading.feature — Missing geographic output is reported for each check


@given("a representative-point task with no output", target_fixture="output")
def missing_point_output(tmp_path: Path, pilot_task_paths: dict[str, Path]) -> dict:
    return {"task": pilot_task_paths["prep-axis-order-001"], "directory": tmp_path}


@then("each grading check reports that the output could not be assessed")
def missing_output_explained(verdict) -> None:
    assert not verdict.passed
    assert verdict.checks
    assert all("could not evaluate assertion" in check.message for check in verdict.checks)
