"""Task-suite v1 validation for the prepared GEOAI pilot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, SchemaError
from pydantic.dataclasses import dataclass

from experiment.adapters.task_repository import TaskLoadError, read_task_document

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


def _schema_path_suffix(path_parts) -> str:
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in path_parts)


def _schema_validation_issues(
    value: Any, schema: dict[str, Any], path: str = "$"
) -> list[ValidationIssue]:
    """Apply the standard JSON Schema draft used by the task-suite contract."""
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: (tuple(map(str, error.absolute_path)), error.message),
    )
    return [
        ValidationIssue(path=path + _schema_path_suffix(error.absolute_path), message=error.message)
        for error in errors
    ]


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
    assertions = oracle.get("assertions", [])
    if not isinstance(assertions, list):
        assertions = []
    fixture_paths = _fixture_paths(task, assertions)
    issues.extend(_fixture_file_issues(task_id, root, fixture_paths))
    for assertion in assertions:
        issues.extend(_assertion_issues(task_id, task_path, root, assertion))
    return issues


def _input_fixture(task: dict[str, Any]) -> object:
    fixtures = task.get("fixtures", {})
    if not isinstance(fixtures, dict):
        return ""
    return fixtures.get("input", "")


def _assertion_fixture_paths(assertions: list[Any]) -> list[object]:
    return [
        assertion.get("fixture", "")
        for assertion in assertions
        if isinstance(assertion, dict) and assertion.get("fixture")
    ]


def _fixture_paths(task: dict[str, Any], assertions: list[Any]) -> list[str]:
    candidates = [_input_fixture(task), *_assertion_fixture_paths(assertions)]
    return [relative for relative in candidates if isinstance(relative, str) and relative]


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
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return None, [ValidationIssue(str(schema_path), f"invalid JSON schema: {exc.message}")]
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
        # The validator reports a malformed task as an *issue*; it must not raise.
        # That is why it goes through the repository's document reader rather
        # than load_task, which validates and would raise on the very files this
        # command exists to describe.
        try:
            task = read_task_document(path)
        except TaskLoadError as exc:
            issues.append(ValidationIssue(path.name, exc.reason))
            continue
        task_issues = _schema_validation_issues(task, schema)
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
