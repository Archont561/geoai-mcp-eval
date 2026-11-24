"""Strict 1:1 oracle assertion-to-predicate mapping from committed task YAMLs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiment.adapters import paths
from experiment.adapters.task_repository import load_suite


def _validate_assertion_mapping(
    task_id: str,
    assertion: dict[str, Any],
    mapping: dict[str, str],
    by_predicate: dict[str, str],
) -> None:
    assertion_id = assertion.get("id")
    predicate = assertion.get("predicate")
    if not isinstance(assertion_id, str) or not assertion_id.strip():
        raise ValueError(f"{task_id}: oracle assertion is missing a valid id")
    if not isinstance(predicate, str) or not predicate.strip():
        raise ValueError(f"{task_id}: assertion {assertion_id!r} is missing a predicate mapping")
    if assertion_id in mapping:
        raise ValueError(f"duplicate assertion id {assertion_id!r} across task suite")
    if predicate in by_predicate:
        prev = by_predicate[predicate]
        raise ValueError(
            f"predicate {predicate!r} is not 1:1 (mapped by {prev!r} and {assertion_id!r})"
        )
    mapping[assertion_id] = predicate
    by_predicate[predicate] = assertion_id


def load_predicates(tasks_root: Path | None = None) -> dict[str, str]:
    """Map ``assertion_id -> predicate`` 1:1 across the committed task suite.

    Failing loudly on missing or duplicate predicates prevents silent zero-scoring
    or collapsed columns in downstream analysis DataFrames.
    """
    suite_root = tasks_root if tasks_root is not None else paths.tasks_root()
    mapping: dict[str, str] = {}
    by_predicate: dict[str, str] = {}
    for task in load_suite(suite_root):
        for assertion in task.oracle.assertions:
            _validate_assertion_mapping(task.id, assertion, mapping, by_predicate)
    return mapping


def task_predicates(tasks_root: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Map ``task_id -> sorted tuple of predicate slugs`` for per-task filtering."""
    suite_root = tasks_root if tasks_root is not None else paths.tasks_root()
    mapping = load_predicates(suite_root)
    per_task: dict[str, tuple[str, ...]] = {}
    for task in load_suite(suite_root):
        slugs = sorted(mapping[str(assertion["id"])] for assertion in task.oracle.assertions)
        per_task[task.id] = tuple(slugs)
    return per_task
