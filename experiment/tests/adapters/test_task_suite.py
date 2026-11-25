"""Behavioral tests for the pilot task-suite validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters.task_suite import (
    _resolve_inside,
    _schema_validation_issues,
    validate_suite,
)

UTF8 = "utf-8"
TYPE_KEY = "type"
AXIS_TASK_YAML = "prep-axis-order-001.yaml"
SAFE_SEGMENTS = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=8),
    min_size=1,
    max_size=3,
)


@given(segments=SAFE_SEGMENTS)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resolve_inside_accepts_arbitrary_nested_relative_paths(
    tmp_path: Path, segments: list[str]
) -> None:
    rel = "/".join(segments)
    resolved = _resolve_inside(tmp_path, rel)
    assert resolved.is_relative_to(tmp_path.resolve())


def test_jsonschema_validation_and_path_containment(tmp_path: Path) -> None:
    assert _resolve_inside(tmp_path, "nested/file").parent == tmp_path / "nested"
    for unsafe in ("/absolute", "../outside"):
        with pytest.raises(ValueError):
            _resolve_inside(tmp_path, unsafe)


def test_standard_jsonschema_keywords_are_supported() -> None:
    issues = _schema_validation_issues(
        {"name": "", "count": -1, "tags": ["x", "x"], "extra": 1},
        {
            TYPE_KEY: "object",
            "required": ["missing"],
            "additionalProperties": False,
            "properties": {
                "name": {TYPE_KEY: "string", "minLength": 1, "pattern": "^[A-Z]+$"},
                "count": {TYPE_KEY: "integer", "minimum": 0, "maximum": 2},
                "tags": {TYPE_KEY: "array", "uniqueItems": True, "items": {TYPE_KEY: "string"}},
            },
            "allOf": [{"minProperties": 5}],
        },
    )
    messages = " ".join(issue.message for issue in issues)
    assert "missing' is a required property" in messages
    assert "Additional properties are not allowed" in messages
    assert "should be non-empty" in messages
    assert "does not match" in messages
    assert "less than the minimum" in messages
    assert "has non-unique elements" in messages
    assert "does not have enough properties" in messages
    issues = _schema_validation_issues(1, {TYPE_KEY: "string"})
    assert "is not of type 'string'" in issues[0].message


def test_validator_reports_duplicate_ids_and_unimplemented_oracle(copied_task_suite: Path) -> None:
    first = copied_task_suite / AXIS_TASK_YAML
    second = copied_task_suite / "analysis-de9im-001.yaml"
    task = yaml.safe_load(second.read_text(encoding=UTF8))
    task["id"] = "prep-axis-order-001"
    task["oracle"]["assertions"][0][TYPE_KEY] = "not-implemented"
    second.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)

    report = validate_suite(copied_task_suite)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert not report.passed
    assert first.name in messages
    assert "duplicate task ID" in messages
    assert "unimplemented type" in messages


def test_validator_reports_schema_and_unsafe_fixture_path_errors(copied_task_suite: Path) -> None:
    path = copied_task_suite / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    del task["title"]
    task["fixtures"]["input"] = "../../outside.geojson"
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)

    report = validate_suite(copied_task_suite)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert "'title' is a required property" in messages
    assert "escapes the task-suite directory" in messages


def test_validator_rejects_schema_that_is_not_valid_json_schema(copied_task_suite: Path) -> None:
    (copied_task_suite / "schema-v1.json").write_text("{not json", encoding=UTF8)
    report = validate_suite(copied_task_suite)
    assert not report.passed
    assert report.task_count == 0
    assert any("invalid JSON schema" in issue.message for issue in report.issues)

    (copied_task_suite / "schema-v1.json").write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", TYPE_KEY: 5}),
        encoding=UTF8,
    )
    report = validate_suite(copied_task_suite)
    assert not report.passed
    assert report.task_count == 0
    assert any("invalid JSON schema" in issue.message for issue in report.issues)


def test_validator_rejects_empty_suite_and_non_mapping_task(copied_task_suite: Path) -> None:
    for path in copied_task_suite.glob("*.yaml"):
        path.unlink()
    report = validate_suite(copied_task_suite)
    assert not report.passed
    assert any("no task YAML files found" in issue.message for issue in report.issues)

    (copied_task_suite / AXIS_TASK_YAML).write_text("- not\n- a mapping\n", encoding=UTF8)
    report = validate_suite(copied_task_suite)
    assert not report.passed
    assert any("task document must be a YAML mapping" in issue.message for issue in report.issues)


def test_validator_reports_invalid_fixture_and_completed_baseline(copied_task_suite: Path) -> None:
    path = copied_task_suite / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    task["human_baseline"]["status"] = "complete"
    task["human_baseline"]["artifact_dir"] = "baselines/missing"
    fixture_path = copied_task_suite / task["fixtures"]["input"]
    fixture_path.write_text(json.dumps({TYPE_KEY: "FeatureCollection", "features": "bad"}))
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)

    report = validate_suite(copied_task_suite)
    messages = "\n".join(str(issue) for issue in report.issues)
    assert "completed human baseline artifact_dir does not exist" in messages
    assert "fixture is not a GeoJSON FeatureCollection" in messages


def test_validator_reports_non_geojson_and_malformed_features(copied_task_suite: Path) -> None:
    path = copied_task_suite / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    fixture_path = copied_task_suite / task["fixtures"]["input"]
    fixture_path.write_text(
        json.dumps({TYPE_KEY: "FeatureCollection", "features": [{"properties": []}]})
    )
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)
    report = validate_suite(copied_task_suite)
    assert any("cannot read fixture" in issue.message for issue in report.issues)

    fixture_path.write_text(json.dumps({TYPE_KEY: "Feature", "features": []}))
    report = validate_suite(copied_task_suite)
    assert any("not a GeoJSON FeatureCollection" in issue.message for issue in report.issues)


def test_validator_reports_unsafe_oracle_paths_and_missing_assertion_fields(
    copied_task_suite: Path,
) -> None:
    path = copied_task_suite / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    assertion = task["oracle"]["assertions"][1]
    del assertion["id_field"]
    assertion["output"] = "../../outside.json"
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)
    report = validate_suite(copied_task_suite)
    messages = " ".join(issue.message for issue in report.issues)
    assert "missing 'id_field'" in messages
    assert "unsafe output path" in messages


def test_validator_covers_non_dict_oracle_and_invalid_type_fields(copied_task_suite: Path) -> None:
    path = copied_task_suite / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    task["oracle"] = []
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)
    report = validate_suite(copied_task_suite)
    assert any("is not of type 'object'" in issue.message for issue in report.issues)

    task["oracle"] = {
        "determinism_runs": 3,
        "assertions": [
            {
                "id": "bad",
                TYPE_KEY: "de9im_relation",
                "expected_relation": "crosses",
                "output": "out.json",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)
    report = validate_suite(copied_task_suite)
    messages = " ".join(issue.message for issue in report.issues)
    assert "unsupported relation name" in messages
    assert "missing 'fixture'" in messages


def test_validator_reports_parse_errors_and_missing_schema(copied_task_suite: Path) -> None:
    (copied_task_suite / AXIS_TASK_YAML).write_text("id: [broken\n", encoding=UTF8)
    report = validate_suite(copied_task_suite)
    assert any("cannot parse YAML" in issue.message for issue in report.issues)

    (copied_task_suite / "schema-v1.json").unlink()
    report = validate_suite(copied_task_suite)
    assert any("cannot read schema" in issue.message for issue in report.issues)


def test_validator_does_not_crash_on_wrongly_shaped_yaml_values(copied_task_suite: Path) -> None:
    path = copied_task_suite / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    task["fixtures"] = []
    task["oracle"]["assertions"] = 5
    task["required_traps"] = [[]]
    task["family"] = []
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)

    report = validate_suite(copied_task_suite)
    assert not report.passed
    assert any("is not of type" in issue.message for issue in report.issues)

    (copied_task_suite / "schema-v1.json").write_text("[]", encoding=UTF8)
    report = validate_suite(copied_task_suite)
    assert any("schema root must be an object" in issue.message for issue in report.issues)
