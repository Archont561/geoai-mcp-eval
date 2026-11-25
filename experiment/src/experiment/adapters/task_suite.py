"""Filesystem & JSON-Schema task-suite validation adapter (delegates rules to domain)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from experiment.adapters.task_repository import TaskLoadError, read_task_document
from experiment.domain.task_validation import (
    ORACLE_ASSERTION_FIELDS,
    REQUIRED_PILOT_TRAPS,
    SUPPORTED_ORACLE_TYPES,
    ValidationIssue,
    ValidationReport,
    extract_fixture_paths,
    validate_assertion_semantics,
    validate_fixture_document,
    validate_suite_coverage,
)

__all__ = [
    "ORACLE_ASSERTION_FIELDS",
    "REQUIRED_PILOT_TRAPS",
    "SUPPORTED_ORACLE_TYPES",
    "ValidationIssue",
    "ValidationReport",
    "validate_suite",
]


def _schema_path_suffix(path_parts: Any) -> str:
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
                ValidationIssue(
                    path=task_id, message="completed human baseline artifact_dir does not exist"
                )
            ]
    except (KeyError, TypeError, ValueError) as exc:
        return [
            ValidationIssue(path=task_id, message=f"invalid human baseline artifact_dir: {exc}")
        ]
    return []


def _fixture_file_issue(task_id: str, root: Path, relative: str) -> ValidationIssue | None:
    try:
        fixture = _resolve_inside(root, relative)
        if not fixture.is_file():
            return ValidationIssue(path=task_id, message=f"fixture does not exist: {relative}")
        data = json.loads(fixture.read_text(encoding="utf-8"))
        return validate_fixture_document(task_id, relative, data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
        return ValidationIssue(path=task_id, message=f"cannot read fixture {relative}: {exc}")


def _fixture_file_issues(
    task_id: str, root: Path, fixture_paths: list[str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for relative in sorted(set(fixture_paths)):
        issue = _fixture_file_issue(task_id, root, relative)
        if issue is not None:
            issues.append(issue)
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
                    path=task_id,
                    message=f"oracle assertion {assertion_id!r} has unsafe {key} path: {exc}",
                )
            )
    return issues


def _assertion_issues(
    task_id: str, task_path: Path, root: Path, assertion: Any
) -> list[ValidationIssue]:
    if not isinstance(assertion, dict):
        return []
    issues = validate_assertion_semantics(task_id, assertion)
    if assertion.get("type") not in SUPPORTED_ORACLE_TYPES:
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
    fixture_paths = extract_fixture_paths(task, assertions)
    issues.extend(_fixture_file_issues(task_id, root, fixture_paths))
    for assertion in assertions:
        issues.extend(_assertion_issues(task_id, task_path, root, assertion))
    return issues


def _read_schema(root: Path) -> tuple[dict[str, Any] | None, list[ValidationIssue]]:
    schema_path = root / "schema-v1.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [ValidationIssue(path=str(schema_path), message=f"cannot read schema: {exc}")]
    except json.JSONDecodeError as exc:
        return None, [ValidationIssue(path=str(schema_path), message=f"invalid JSON schema: {exc}")]
    if not isinstance(schema, dict):
        return None, [
            ValidationIssue(path=str(schema_path), message="JSON schema root must be an object")
        ]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return None, [
            ValidationIssue(path=str(schema_path), message=f"invalid JSON schema: {exc.message}")
        ]
    return schema, []


def _load_task_files(
    root: Path, schema: dict[str, Any]
) -> tuple[list[tuple[str, dict[str, Any]]], list[ValidationIssue]]:
    tasks: list[tuple[str, dict[str, Any]]] = []
    issues: list[ValidationIssue] = []
    files = sorted(root.glob("*.yaml"))
    if not files:
        issues.append(ValidationIssue(path=str(root), message="no task YAML files found"))
    for path in files:
        # Report malformed tasks as issues rather than raising.
        try:
            task = read_task_document(path)
        except TaskLoadError as exc:
            issues.append(ValidationIssue(path=path.name, message=exc.reason))
            continue
        for issue in _schema_validation_issues(task, schema):
            msg = issue.message if issue.path == "$" else f"{issue.path}: {issue.message}"
            issues.append(ValidationIssue(path=path.name, message=msg))
        issues.extend(_task_semantic_issues(task, path, root))
        tasks.append((path.name, task))
    return tasks, issues


def validate_suite(root: Path) -> ValidationReport:
    """Validate all task YAML files, fixtures, IDs, oracle types, and required traps."""
    root = root.resolve()
    schema, schema_issues = _read_schema(root)
    if schema is None:
        return ValidationReport(task_count=0, traps_found=frozenset(), issues=tuple(schema_issues))
    tasks, issues = _load_task_files(root, schema)
    traps_found, coverage_issues = validate_suite_coverage(tasks, str(root))
    return ValidationReport(
        task_count=len(tasks), traps_found=traps_found, issues=tuple(issues + coverage_issues)
    )
