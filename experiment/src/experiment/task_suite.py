"""Task-suite v1 validation for the prepared GEOAI pilot."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_SCHEMA_KEYWORDS = {
    "$id",
    "$schema",
    "additionalProperties",
    "const",
    "enum",
    "items",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "uniqueItems",
}
SUPPORTED_ORACLE_TYPES = {
    "de9im_relation",
    "geojson_feature_count",
    "jenks_classification",
    "representative_point_matches",
}
REQUIRED_PILOT_TRAPS = {
    "crs-axis-order",
    "jenks-classification",
    "topology-de9im",
}
ORACLE_ASSERTION_FIELDS = {
    "geojson_feature_count": {"output", "expected"},
    "representative_point_matches": {
        "fixture",
        "output",
        "id_field",
        "feature_id",
        "preserve_fields",
        "tolerance_degrees",
    },
    "de9im_relation": {
        "fixture",
        "output",
        "id_field",
        "left_id",
        "right_id",
        "expected_relation",
        "expected_matrix",
    },
    "jenks_classification": {"fixture", "output", "id_field", "value_field", "class_count"},
}


@dataclass(frozen=True)
class ValidationIssue:
    """One actionable task-suite validation error."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class ValidationReport:
    """Summary of a task-suite validation run."""

    task_count: int
    traps_found: frozenset[str]
    issues: tuple[ValidationIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _validate_scalar(value: Any, schema: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "const" in schema and value != schema["const"]:
        issues.append(ValidationIssue(path, f"must equal {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        issues.append(ValidationIssue(path, f"must be one of {schema['enum']!r}"))
    if isinstance(value, str):
        issues.extend(_validate_string(value, schema, path))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        issues.extend(_validate_number(value, schema, path))
    return issues


def _validate_string(value: str, schema: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(value) < schema.get("minLength", 0):
        issues.append(ValidationIssue(path, "is shorter than the minimum length"))
    if len(value) > schema.get("maxLength", float("inf")):
        issues.append(ValidationIssue(path, "is longer than the maximum length"))
    pattern = schema.get("pattern")
    if pattern and re.search(pattern, value) is None:
        issues.append(ValidationIssue(path, f"does not match pattern {pattern!r}"))
    return issues


def _validate_number(
    value: int | float, schema: dict[str, Any], path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if value < schema.get("minimum", float("-inf")):
        issues.append(ValidationIssue(path, f"must be at least {schema['minimum']}"))
    if value > schema.get("maximum", float("inf")):
        issues.append(ValidationIssue(path, f"must be at most {schema['maximum']}"))
    return issues


def _validate_object(
    value: dict[str, Any], schema: dict[str, Any], path: str
) -> list[ValidationIssue]:
    issues = [
        ValidationIssue(path, f"missing required field {key!r}")
        for key in schema.get("required", [])
        if key not in value
    ]
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        issues.extend(
            ValidationIssue(f"{path}.{key}", "additional field is not allowed")
            for key in value.keys() - properties.keys()
        )
    for key, child_schema in properties.items():
        if key in value:
            issues.extend(_validate_instance(value[key], child_schema, f"{path}.{key}"))
    return issues


def _validate_array(value: list[Any], schema: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(value) < schema.get("minItems", 0):
        issues.append(ValidationIssue(path, "has fewer items than the minimum"))
    if len(value) > schema.get("maxItems", float("inf")):
        issues.append(ValidationIssue(path, "has more items than the maximum"))
    if schema.get("uniqueItems") and len(
        {json.dumps(item, sort_keys=True) for item in value}
    ) != len(value):
        issues.append(ValidationIssue(path, "items must be unique"))
    item_schema = schema.get("items")
    if item_schema:
        for index, item in enumerate(value):
            issues.extend(_validate_instance(item, item_schema, f"{path}[{index}]"))
    return issues


def _validate_instance(value: Any, schema: dict[str, Any], path: str) -> list[ValidationIssue]:
    """Validate the deliberately small JSON Schema keyword subset used by v1."""
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unsupported:
        return [
            ValidationIssue(
                path, f"schema uses unsupported keyword(s): {', '.join(sorted(unsupported))}"
            )
        ]
    expected_type = schema.get("type")
    if expected_type is not None:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_json_type_matches(value, kind) for kind in types):
            return [ValidationIssue(path, f"expected type {' or '.join(types)}")]

    issues = _validate_scalar(value, schema, path)
    if isinstance(value, dict):
        issues.extend(_validate_object(value, schema, path))
    if isinstance(value, list):
        issues.extend(_validate_array(value, schema, path))
    return issues


def _resolve_inside(root: Path, relative: str) -> Path:
    candidate_path = Path(relative)
    if candidate_path.is_absolute():
        raise ValueError("path must be relative")
    candidate = (root / candidate_path).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("path escapes the task-suite directory")
    return candidate


def _baseline_issues(task: dict[str, Any], task_id: str, root: Path) -> list[ValidationIssue]:
    baseline = task.get("human_baseline", {})
    if not isinstance(baseline, dict) or baseline.get("status") != "complete":
        return []
    try:
        baseline_dir = _resolve_inside(root, baseline["artifact_dir"])
        if not baseline_dir.is_dir():
            return [
                ValidationIssue(task_id, "completed human baseline artifact_dir does not exist")
            ]
    except (KeyError, TypeError, ValueError) as exc:
        return [ValidationIssue(task_id, f"invalid human baseline artifact_dir: {exc}")]
    return []


def _fixture_file_issue(task_id: str, root: Path, relative: str) -> ValidationIssue | None:
    try:
        fixture = _resolve_inside(root, relative)
        if not fixture.is_file():
            return ValidationIssue(task_id, f"fixture does not exist: {relative}")
        data = json.loads(fixture.read_text(encoding="utf-8"))
        is_feature_collection = (
            isinstance(data, dict)
            and data.get("type") == "FeatureCollection"
            and isinstance(data.get("features"), list)
        )
        if not is_feature_collection:
            return ValidationIssue(
                task_id, f"fixture is not a GeoJSON FeatureCollection: {relative}"
            )
        feature_ids = [feature.get("properties", {}).get("ISO_A3") for feature in data["features"]]
        if None in feature_ids or len(feature_ids) != len(set(feature_ids)):
            return ValidationIssue(
                task_id, f"fixture ISO_A3 values must be present and unique: {relative}"
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
        return ValidationIssue(task_id, f"cannot read fixture {relative}: {exc}")
    return None


def _fixture_file_issues(
    task_id: str, root: Path, fixture_paths: list[str]
) -> list[ValidationIssue]:
    issues = []
    for relative in sorted(set(fixture_paths)):
        issue = _fixture_file_issue(task_id, root, relative)
        if issue is not None:
            issues.append(issue)
    return issues


def _assertion_type_issues(
    task_id: str, assertion_id: object, oracle_type: object, assertion: dict[str, Any]
) -> list[ValidationIssue]:
    if not isinstance(oracle_type, str) or oracle_type not in SUPPORTED_ORACLE_TYPES:
        return [
            ValidationIssue(
                task_id,
                f"oracle assertion {assertion_id!r} uses unimplemented type {oracle_type!r}",
            )
        ]
    issues = [
        ValidationIssue(task_id, f"oracle assertion {assertion_id!r} is missing {field!r}")
        for field in sorted(ORACLE_ASSERTION_FIELDS[oracle_type] - assertion.keys())
    ]
    issues.extend(_assertion_value_issues(task_id, assertion_id, oracle_type, assertion))
    return issues


def _assertion_value_issues(
    task_id: str, assertion_id: object, oracle_type: str, assertion: dict[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    supported_relations = {"touches", "intersects", "equals", "disjoint"}
    if (
        oracle_type == "de9im_relation"
        and assertion.get("expected_relation") not in supported_relations
    ):
        issues.append(
            ValidationIssue(
                task_id, f"oracle assertion {assertion_id!r} has unsupported relation name"
            )
        )
    if oracle_type == "jenks_classification" and type(assertion.get("class_count")) is not int:
        issues.append(
            ValidationIssue(
                task_id,
                f"oracle assertion {assertion_id!r} class_count must be an integer",
            )
        )
    return issues


def _assertion_path_issues(
    task_id: str, task_path: Path, root: Path, assertion: dict[str, Any]
) -> list[ValidationIssue]:
    assertion_id = assertion.get("id", "<unnamed>")
    issues: list[ValidationIssue] = []
    for key in ("fixture", "output"):
        if key not in assertion:
            continue
        allowed_root = root if key == "fixture" else task_path.parent
        try:
            _resolve_inside(allowed_root, assertion[key])
        except (TypeError, ValueError) as exc:
            issues.append(
                ValidationIssue(
                    task_id,
                    f"oracle assertion {assertion_id!r} has unsafe {key} path: {exc}",
                )
            )
    return issues


def _assertion_issues(
    task_id: str,
    task_path: Path,
    root: Path,
    assertion: Any,
) -> list[ValidationIssue]:
    if not isinstance(assertion, dict):
        return []
    assertion_id = assertion.get("id", "<unnamed>")
    oracle_type = assertion.get("type")
    issues = _assertion_type_issues(task_id, assertion_id, oracle_type, assertion)
    if oracle_type not in SUPPORTED_ORACLE_TYPES:
        return issues
    issues.extend(_assertion_path_issues(task_id, task_path, root, assertion))
    return issues


def _task_semantic_issues(
    task: dict[str, Any], task_path: Path, root: Path
) -> list[ValidationIssue]:
    task_id = task.get("id", task_path.stem)
    oracle = task.get("oracle", {})
    if not isinstance(oracle, dict):
        return []
    issues = _baseline_issues(task, task_id, root)
    fixtures = task.get("fixtures", {})
    input_fixture = fixtures.get("input", "") if isinstance(fixtures, dict) else ""
    assertions = oracle.get("assertions", [])
    if not isinstance(assertions, list):
        assertions = []
    fixture_paths = [input_fixture]
    fixture_paths.extend(
        assertion.get("fixture", "")
        for assertion in assertions
        if isinstance(assertion, dict) and assertion.get("fixture")
    )
    fixture_paths = [
        relative for relative in fixture_paths if isinstance(relative, str) and relative
    ]
    issues.extend(_fixture_file_issues(task_id, root, fixture_paths))
    for assertion in assertions:
        issues.extend(_assertion_issues(task_id, task_path, root, assertion))
    return issues


def _read_schema(root: Path) -> tuple[dict[str, Any] | None, list[ValidationIssue]]:
    schema_path = root / "schema-v1.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [ValidationIssue(str(schema_path), f"cannot read schema: {exc}")]
    except json.JSONDecodeError as exc:
        return None, [ValidationIssue(str(schema_path), f"invalid JSON schema: {exc}")]
    if not isinstance(schema, dict):
        return None, [ValidationIssue(str(schema_path), "JSON schema root must be an object")]
    return schema, []


def _load_task_files(
    root: Path, schema: dict[str, Any]
) -> tuple[list[tuple[Path, dict[str, Any]]], list[ValidationIssue]]:
    tasks: list[tuple[Path, dict[str, Any]]] = []
    issues: list[ValidationIssue] = []
    files = sorted(root.glob("*.yaml"))
    if not files:
        issues.append(ValidationIssue(str(root), "no task YAML files found"))
    for path in files:
        try:
            task = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            issues.append(ValidationIssue(path.name, f"cannot parse YAML: {exc}"))
            continue
        if not isinstance(task, dict):
            issues.append(ValidationIssue(path.name, "task document must be a YAML mapping"))
            continue
        task_issues = _validate_instance(task, schema, "$")
        issues.extend(
            ValidationIssue(
                path.name,
                issue.message if issue.path == "$" else f"{issue.path}: {issue.message}",
            )
            for issue in task_issues
        )
        issues.extend(_task_semantic_issues(task, path, root))
        tasks.append((path, task))
    return tasks, issues


def _task_id_issue(
    path: Path, task: dict[str, Any], identifiers: dict[str, str]
) -> ValidationIssue | None:
    task_id = task.get("id")
    if not isinstance(task_id, str):
        return None
    if task_id in identifiers:
        return ValidationIssue(
            path.name,
            f"duplicate task ID {task_id!r}; first used by {identifiers[task_id]}",
        )
    identifiers[task_id] = path.name
    return None


def _required_trap_issues(root: Path, traps_found: set[str]) -> list[ValidationIssue]:
    return [
        ValidationIssue(str(root), f"required pilot trap is not covered: {missing}")
        for missing in sorted(REQUIRED_PILOT_TRAPS - traps_found)
    ]


def _family_coverage_issues(
    root: Path, tasks: list[tuple[Path, dict[str, Any]]]
) -> list[ValidationIssue]:
    found_families = {
        task.get("family") for _, task in tasks if isinstance(task.get("family"), str)
    }
    expected_families = {"P", "A", "C"}
    return [
        ValidationIssue(str(root), f"pilot suite is missing task family {missing}")
        for missing in sorted(expected_families - found_families)
    ]


def _suite_coverage(
    tasks: list[tuple[Path, dict[str, Any]]], root: Path
) -> tuple[frozenset[str], list[ValidationIssue]]:
    identifiers: dict[str, str] = {}
    traps_found: set[str] = set()
    issues: list[ValidationIssue] = []
    for path, task in tasks:
        id_issue = _task_id_issue(path, task, identifiers)
        if id_issue is not None:
            issues.append(id_issue)
        task_traps = task.get("required_traps", [])
        if isinstance(task_traps, list):
            traps_found.update(trap for trap in task_traps if isinstance(trap, str))
    issues.extend(_required_trap_issues(root, traps_found))
    issues.extend(_family_coverage_issues(root, tasks))
    return frozenset(traps_found), issues


def validate_suite(root: Path) -> ValidationReport:
    """Validate all task YAML files, fixtures, IDs, oracle types, and required traps."""
    root = root.resolve()
    schema, schema_issues = _read_schema(root)
    if schema is None:
        return ValidationReport(0, frozenset(), tuple(schema_issues))
    tasks, issues = _load_task_files(root, schema)
    traps_found, coverage_issues = _suite_coverage(tasks, root)
    return ValidationReport(
        len(tasks),
        traps_found,
        tuple(issues + coverage_issues),
    )


def main(argv: list[str] | None = None) -> int:
    """Provide a small standalone validation entry point for tools and CI."""
    parser = argparse.ArgumentParser(
        description="Validate GEOAI pilot task-suite YAML and fixtures."
    )
    parser.add_argument("--root", type=Path, default=Path("experiment/tasks"))
    args = parser.parse_args(argv)
    report = validate_suite(args.root)
    if report.passed:
        traps = ", ".join(sorted(report.traps_found))
        print(f"Task suite valid: {report.task_count} tasks; pilot traps covered: {traps}")
        return 0
    for issue in report.issues:
        print(f"ERROR: {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
