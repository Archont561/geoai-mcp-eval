"""Pure domain rules for task-suite semantic and coverage validation (GEO-021).

No filesystem, YAML, or JSON Schema library imports: this module validates
already-loaded task and fixture documents so ``adapters/task_suite.py`` stays
focused strictly on I/O, JSON Schema checks, and path containment.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

SUPPORTED_ORACLE_TYPES = frozenset(
    {
        "de9im_relation",
        "geojson_feature_count",
        "jenks_classification",
        "representative_point_matches",
    }
)
REQUIRED_PILOT_TRAPS = frozenset(
    {
        "crs-axis-order",
        "jenks-classification",
        "topology-de9im",
    }
)
REQUIRED_TASK_FAMILIES = frozenset({"P", "A", "C"})
SUPPORTED_DE9IM_RELATIONS = frozenset({"touches", "intersects", "equals", "disjoint"})
ORACLE_ASSERTION_FIELDS: dict[str, set[str]] = {
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


class ValidationIssue(BaseModel):
    """One actionable task-suite validation error."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class ValidationReport(BaseModel):
    """Summary of a task-suite validation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_count: int
    traps_found: frozenset[str]
    issues: tuple[ValidationIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def validate_fixture_document(task_id: str, relative: str, data: object) -> ValidationIssue | None:
    """Validate that a parsed GeoJSON fixture is a FeatureCollection with unique ``ISO_A3`` IDs."""
    if not isinstance(data, dict):
        return ValidationIssue(
            path=task_id, message=f"fixture is not a GeoJSON FeatureCollection: {relative}"
        )
    features = data.get("features")
    if data.get("type") != "FeatureCollection" or not isinstance(features, list):
        return ValidationIssue(
            path=task_id, message=f"fixture is not a GeoJSON FeatureCollection: {relative}"
        )
    feature_ids = [feature.get("properties", {}).get("ISO_A3") for feature in features]
    if None in feature_ids or len(feature_ids) != len(set(feature_ids)):
        return ValidationIssue(
            path=task_id, message=f"fixture ISO_A3 values must be present and unique: {relative}"
        )
    return None


def _assertion_value_issues(
    task_id: str, assertion_id: object, oracle_type: str, assertion: dict[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if (
        oracle_type == "de9im_relation"
        and assertion.get("expected_relation") not in SUPPORTED_DE9IM_RELATIONS
    ):
        issues.append(
            ValidationIssue(
                path=task_id,
                message=f"oracle assertion {assertion_id!r} has unsupported relation name",
            )
        )
    if oracle_type == "jenks_classification" and type(assertion.get("class_count")) is not int:
        issues.append(
            ValidationIssue(
                path=task_id,
                message=f"oracle assertion {assertion_id!r} class_count must be an integer",
            )
        )
    return issues


def validate_assertion_semantics(task_id: str, assertion: Any) -> list[ValidationIssue]:
    """Check one oracle assertion's type, required fields, and domain value constraints."""
    if not isinstance(assertion, dict):
        return []
    assertion_id = assertion.get("id", "<unnamed>")
    oracle_type = assertion.get("type")
    if not isinstance(oracle_type, str) or oracle_type not in SUPPORTED_ORACLE_TYPES:
        msg = f"oracle assertion {assertion_id!r} uses unimplemented type {oracle_type!r}"
        return [ValidationIssue(path=task_id, message=msg)]
    issues = [
        ValidationIssue(
            path=task_id, message=f"oracle assertion {assertion_id!r} is missing {field!r}"
        )
        for field in sorted(ORACLE_ASSERTION_FIELDS[oracle_type] - assertion.keys())
    ]
    issues.extend(_assertion_value_issues(task_id, assertion_id, oracle_type, assertion))
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


def extract_fixture_paths(task: dict[str, Any], assertions: list[Any]) -> list[str]:
    """Collect all non-empty relative fixture paths referenced by a task and its assertions."""
    candidates = [_input_fixture(task), *_assertion_fixture_paths(assertions)]
    return [relative for relative in candidates if isinstance(relative, str) and relative]


def _task_id_issue(
    filename: str, task: dict[str, Any], identifiers: dict[str, str]
) -> ValidationIssue | None:
    task_id = task.get("id")
    if not isinstance(task_id, str):
        return None
    if task_id in identifiers:
        return ValidationIssue(
            path=filename,
            message=f"duplicate task ID {task_id!r}; first used by {identifiers[task_id]}",
        )
    identifiers[task_id] = filename
    return None


def _required_trap_issues(suite_label: str, traps_found: set[str]) -> list[ValidationIssue]:
    return [
        ValidationIssue(path=suite_label, message=f"required pilot trap is not covered: {missing}")
        for missing in sorted(REQUIRED_PILOT_TRAPS - traps_found)
    ]


def _family_coverage_issues(
    suite_label: str, tasks: list[tuple[str, dict[str, Any]]]
) -> list[ValidationIssue]:
    found_families = {
        task.get("family") for _, task in tasks if isinstance(task.get("family"), str)
    }
    return [
        ValidationIssue(path=suite_label, message=f"pilot suite is missing task family {missing}")
        for missing in sorted(REQUIRED_TASK_FAMILIES - found_families)
    ]


def validate_suite_coverage(
    tasks: list[tuple[str, dict[str, Any]]], suite_label: str
) -> tuple[frozenset[str], list[ValidationIssue]]:
    """Verify unique task IDs, required pilot trap coverage, and family coverage across tasks."""
    identifiers: dict[str, str] = {}
    traps_found: set[str] = set()
    issues: list[ValidationIssue] = []
    for filename, task in tasks:
        id_issue = _task_id_issue(filename, task, identifiers)
        if id_issue is not None:
            issues.append(id_issue)
        task_traps = task.get("required_traps", [])
        if isinstance(task_traps, list):
            traps_found.update(trap for trap in task_traps if isinstance(trap, str))
    issues.extend(_required_trap_issues(suite_label, traps_found))
    issues.extend(_family_coverage_issues(suite_label, tasks))
    return frozenset(traps_found), issues
