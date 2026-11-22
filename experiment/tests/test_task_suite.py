"""Behavioral tests for the pilot task-suite validator."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from experiment.task_suite import (
    _json_type_matches,
    _resolve_inside,
    _validate_instance,
    main,
    validate_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"


def copy_suite(tmp_path: Path) -> Path:
    destination = tmp_path / "tasks"
    shutil.copytree(TASK_ROOT, destination)
    return destination


def write_task(path: Path, task: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")


def test_json_type_matching_and_path_containment(tmp_path: Path) -> None:
    assert _json_type_matches(None, "null")
    assert _json_type_matches(False, "boolean")
    assert _json_type_matches(2, "integer")
    assert not _json_type_matches(True, "integer")
    assert _json_type_matches(2.0, "number")
    assert not _json_type_matches(False, "number")
    assert _json_type_matches("x", "string")
    assert _json_type_matches([], "array")
    assert _json_type_matches({}, "object")
    assert not _json_type_matches(1, "unknown")
    assert _resolve_inside(tmp_path, "nested/file").parent == tmp_path / "nested"
    for unsafe in ("/absolute", "../outside"):
        try:
            _resolve_inside(tmp_path, unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe paths must be rejected")


def test_schema_subset_rejects_keywords_and_checks_constraints() -> None:
    assert _validate_instance("yes", {"type": ["null", "string"]}, "$s") == []
    issues = _validate_instance(
        {"name": "", "count": -1, "tags": ["x", "x"], "extra": 1},
        {
            "type": "object",
            "required": ["missing"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "minLength": 1, "pattern": "^[A-Z]+$"},
                "count": {"type": "integer", "minimum": 0, "maximum": 2},
                "tags": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
            },
        },
        "$s",
    )
    messages = " ".join(issue.message for issue in issues)
    assert "missing required" in messages
    assert "additional field" in messages
    assert "shorter" in messages
    assert "does not match pattern" in messages
    assert "at least" in messages
    assert "items must be unique" in messages
    unsupported = _validate_instance({}, {"type": "object", "allOf": []}, "$s")
    assert len(unsupported) == 1
    assert "unsupported keyword" in unsupported[0].message
    assert _validate_instance(1, {"type": "string"}, "$s")[0].message == "expected type string"


def test_prepared_pilot_suite_validates() -> None:
    report = validate_suite(TASK_ROOT)

    assert report.passed
    assert report.task_count == 3
    assert report.traps_found == frozenset(
        {"crs-axis-order", "topology-de9im", "jenks-classification"}
    )


def test_validator_reports_duplicate_ids_and_unimplemented_oracle(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    first = root / "prep-axis-order-001.yaml"
    second = root / "analysis-de9im-001.yaml"
    task = yaml.safe_load(second.read_text(encoding="utf-8"))
    task["id"] = "prep-axis-order-001"
    task["oracle"]["assertions"][0]["type"] = "not-implemented"
    write_task(second, task)

    report = validate_suite(root)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert not report.passed
    assert first.name in messages
    assert "duplicate task ID" in messages
    assert "unimplemented type" in messages


def test_validator_reports_schema_and_unsafe_fixture_path_errors(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    del task["title"]
    task["fixtures"]["input"] = "../../outside.geojson"
    write_task(path, task)

    report = validate_suite(root)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert "missing required field 'title'" in messages
    assert "escapes the task-suite directory" in messages


def test_validator_reports_invalid_fixture_and_completed_baseline(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    task["human_baseline"]["status"] = "complete"
    task["human_baseline"]["artifact_dir"] = "baselines/missing"
    fixture_path = root / task["fixtures"]["input"]
    fixture_path.write_text(json.dumps({"type": "FeatureCollection", "features": "bad"}))
    write_task(path, task)

    report = validate_suite(root)
    messages = "\n".join(str(issue) for issue in report.issues)

    assert "completed human baseline artifact_dir does not exist" in messages
    assert "fixture is not a GeoJSON FeatureCollection" in messages


def test_validator_reports_non_geojson_and_malformed_features(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    fixture_path = root / task["fixtures"]["input"]
    fixture_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [{"properties": []}]})
    )
    write_task(path, task)
    report = validate_suite(root)
    assert any("cannot read fixture" in issue.message for issue in report.issues)

    fixture_path.write_text(json.dumps({"type": "Feature", "features": []}))
    report = validate_suite(root)
    assert any("not a GeoJSON FeatureCollection" in issue.message for issue in report.issues)


def test_validator_reports_unsafe_oracle_paths_and_missing_assertion_fields(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
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
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    task["oracle"] = []
    write_task(path, task)
    report = validate_suite(root)
    assert any("expected type object" in issue.message for issue in report.issues)

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
    write_task(path, task)
    report = validate_suite(root)
    messages = " ".join(issue.message for issue in report.issues)
    assert "unsupported relation name" in messages
    assert "missing 'fixture'" in messages


def test_validator_reports_parse_errors_missing_schema_and_cli_output(
    tmp_path: Path, capsys
) -> None:
    root = copy_suite(tmp_path)
    (root / "prep-axis-order-001.yaml").write_text("id: [broken\n", encoding="utf-8")
    report = validate_suite(root)
    assert any("cannot parse YAML" in issue.message for issue in report.issues)

    assert main(["--root", str(TASK_ROOT)]) == 0
    assert "Task suite valid: 3 tasks" in capsys.readouterr().out

    (root / "schema-v1.json").unlink()
    report = validate_suite(root)
    assert any("cannot read schema" in issue.message for issue in report.issues)

    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["--root", str(empty)]) == 1
    assert "cannot read schema" in capsys.readouterr().out


def test_validator_does_not_crash_on_wrongly_shaped_yaml_values(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    task["fixtures"] = []
    task["oracle"]["assertions"] = 5
    task["required_traps"] = [[]]
    task["family"] = []
    write_task(path, task)

    report = validate_suite(root)

    assert not report.passed
    assert any("expected type" in issue.message for issue in report.issues)

    (root / "schema-v1.json").write_text("[]", encoding="utf-8")
    report = validate_suite(root)
    assert any("schema root must be an object" in issue.message for issue in report.issues)


def test_validator_reports_missing_pilot_family_and_trap(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    (root / "cartography-jenks-001.yaml").unlink()
    path = root / "prep-axis-order-001.yaml"
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    task["required_traps"] = ["topology-de9im"]
    write_task(path, task)
    report = validate_suite(root)
    messages = " ".join(issue.message for issue in report.issues)
    assert "missing task family C" in messages
    assert "required pilot trap is not covered" in messages
