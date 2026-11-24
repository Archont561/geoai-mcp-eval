"""Behavioral tests for the pilot task-suite validator."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from experiment.task_suite import _resolve_inside, validate_suite

UTF8 = "utf-8"
TYPE_KEY = "type"
AXIS_TASK_YAML = "prep-axis-order-001.yaml"


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"


def copy_suite(tmp_path: Path) -> Path:
    destination = tmp_path / "tasks"
    shutil.copytree(TASK_ROOT, destination)
    return destination


def write_task(path: Path, task: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding=UTF8)


def test_jsonschema_validation_and_path_containment(tmp_path: Path) -> None:
    assert _resolve_inside(tmp_path, "nested/file").parent == tmp_path / "nested"
    for unsafe in ("/absolute", "../outside"):
        try:
            _resolve_inside(tmp_path, unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe paths must be rejected")


def test_standard_jsonschema_keywords_are_supported() -> None:
    from experiment.task_suite import _schema_validation_issues

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


def test_validator_reports_duplicate_ids_and_unimplemented_oracle(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    first = root / AXIS_TASK_YAML
    second = root / "analysis-de9im-001.yaml"
    task = yaml.safe_load(second.read_text(encoding=UTF8))
    task["id"] = "prep-axis-order-001"
    task["oracle"]["assertions"][0][TYPE_KEY] = "not-implemented"
    write_task(second, task)

    report = validate_suite(root)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert not report.passed
    assert first.name in messages
    assert "duplicate task ID" in messages
    assert "unimplemented type" in messages


def test_validator_reports_schema_and_unsafe_fixture_path_errors(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    del task["title"]
    task["fixtures"]["input"] = "../../outside.geojson"
    write_task(path, task)

    report = validate_suite(root)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert "'title' is a required property" in messages
    assert "escapes the task-suite directory" in messages


def test_validator_rejects_schema_that_is_not_valid_json_schema(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    (root / "schema-v1.json").write_text("{not json", encoding=UTF8)
    report = validate_suite(root)

    assert not report.passed
    assert report.task_count == 0
    assert any("invalid JSON schema" in issue.message for issue in report.issues)

    (root / "schema-v1.json").write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", TYPE_KEY: 5}),
        encoding=UTF8,
    )
    report = validate_suite(root)

    assert not report.passed
    assert report.task_count == 0
    assert any("invalid JSON schema" in issue.message for issue in report.issues)


def test_validator_rejects_empty_suite_and_non_mapping_task(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    for path in root.glob("*.yaml"):
        path.unlink()
    report = validate_suite(root)

    assert not report.passed
    assert any("no task YAML files found" in issue.message for issue in report.issues)

    (root / AXIS_TASK_YAML).write_text("- not\n- a mapping\n", encoding=UTF8)
    report = validate_suite(root)

    assert not report.passed
    assert any("task document must be a YAML mapping" in issue.message for issue in report.issues)


def test_validator_reports_invalid_fixture_and_completed_baseline(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    task["human_baseline"]["status"] = "complete"
    task["human_baseline"]["artifact_dir"] = "baselines/missing"
    fixture_path = root / task["fixtures"]["input"]
    fixture_path.write_text(json.dumps({TYPE_KEY: "FeatureCollection", "features": "bad"}))
    write_task(path, task)

    report = validate_suite(root)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert "completed human baseline artifact_dir does not exist" in messages
    assert "fixture is not a GeoJSON FeatureCollection" in messages


def test_validator_reports_non_geojson_and_malformed_features(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    fixture_path = root / task["fixtures"]["input"]
    fixture_path.write_text(
        json.dumps({TYPE_KEY: "FeatureCollection", "features": [{"properties": []}]})
    )
    write_task(path, task)
    report = validate_suite(root)
    assert any("cannot read fixture" in issue.message for issue in report.issues)

    fixture_path.write_text(json.dumps({TYPE_KEY: "Feature", "features": []}))
    report = validate_suite(root)
    assert any("not a GeoJSON FeatureCollection" in issue.message for issue in report.issues)


def test_validator_reports_unsafe_oracle_paths_and_missing_assertion_fields(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    assertion = task["oracle"]["assertions"][1]
    del assertion["id_field"]
    assertion["output"] = "../../outside.json"
    write_task(path, task)
    report = validate_suite(root)
    messages = " ".join(issue.message for issue in report.issues)
    assert "missing 'id_field'" in messages
    assert "unsafe output path" in messages


def test_validator_covers_non_dict_oracle_and_invalid_type_fields(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    task["oracle"] = []
    write_task(path, task)
    report = validate_suite(root)
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
    write_task(path, task)
    report = validate_suite(root)
    messages = " ".join(issue.message for issue in report.issues)
    assert "unsupported relation name" in messages
    assert "missing 'fixture'" in messages


def test_validator_reports_parse_errors_and_missing_schema(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    (root / AXIS_TASK_YAML).write_text("id: [broken\n", encoding=UTF8)
    report = validate_suite(root)
    assert any("cannot parse YAML" in issue.message for issue in report.issues)

    (root / "schema-v1.json").unlink()
    report = validate_suite(root)
    assert any("cannot read schema" in issue.message for issue in report.issues)


def test_validator_does_not_crash_on_wrongly_shaped_yaml_values(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / AXIS_TASK_YAML
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    task["fixtures"] = []
    task["oracle"]["assertions"] = 5
    task["required_traps"] = [[]]
    task["family"] = []
    write_task(path, task)

    report = validate_suite(root)

    assert not report.passed
    assert any("is not of type" in issue.message for issue in report.issues)

    (root / "schema-v1.json").write_text("[]", encoding=UTF8)
    report = validate_suite(root)
    assert any("schema root must be an object" in issue.message for issue in report.issues)
