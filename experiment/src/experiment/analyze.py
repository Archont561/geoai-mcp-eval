"""Analysis data preparation.

score.json is deliberately verbose (per-assertion messages and run provenance).
The analysis stage consumes a flat binary matrix instead: one row per cell and
one 0/1 column per named predicate. Predicate names come from the ``predicate``
key of each oracle assertion in the task YAML — the single source of truth.
Cells score 0 for any assertion that is missing or reported as failed (strict
WSZ semantics; never impute, never NaN).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from experiment.adapters.task_repository import load_suite

KEY_COLUMNS = ("run_id", "task", "arm", "driver", "model")


def load_predicates(tasks_root: Path) -> dict[str, str]:
    """Map assertion id -> predicate slug 1:1 across the task suite.

    Every assertion in the suite must declare a unique, non-empty ``predicate``
    slug, and no two assertions may share the same slug. Failing loudly here
    prevents silent zero-scoring or collapsed columns in downstream analysis.
    """
    mapping: dict[str, str] = {}
    by_predicate: dict[str, str] = {}
    for task in load_suite(tasks_root):
        for assertion in task.oracle.assertions:
            assertion_id = assertion.get("id")
            predicate = assertion.get("predicate")
            if not isinstance(assertion_id, str) or not assertion_id.strip():
                raise ValueError(f"{task.id}: oracle assertion is missing a valid id")
            if not isinstance(predicate, str) or not predicate.strip():
                raise ValueError(
                    f"{task.id}: assertion {assertion_id!r} is missing a predicate mapping"
                )
            if assertion_id in mapping:
                raise ValueError(f"duplicate assertion id {assertion_id!r} across task suite")
            if predicate in by_predicate:
                prev = by_predicate[predicate]
                raise ValueError(
                    f"predicate {predicate!r} is not 1:1 (mapped by {prev!r} and {assertion_id!r})"
                )
            mapping[assertion_id] = predicate
            by_predicate[predicate] = assertion_id
    return mapping


def _check_lookup(checks: Any) -> dict[str, bool]:
    if not isinstance(checks, list):
        return {}
    return {
        str(check.get("assertion_id")): bool(check.get("passed"))
        for check in checks
        if isinstance(check, dict) and check.get("assertion_id") is not None
    }


def flatten_rows(results_root: Path, tasks_root: Path) -> list[dict[str, Any]]:
    """One row per cell: KEY_COLUMNS plus one 0/1 column per predicate."""
    predicates = load_predicates(tasks_root)
    predicate_columns = sorted(set(predicates.values()))
    rows: list[dict[str, Any]] = []
    for score_file in sorted(results_root.rglob("score.json")):
        data = json.loads(score_file.read_text(encoding="utf-8"))
        meta = data.get("meta") if isinstance(data, dict) else None
        if not isinstance(meta, dict) or not isinstance(data.get("checks"), list):
            raise ValueError(f"{score_file}: not a cell score.json (missing meta/checks)")
        by_id = _check_lookup(data["checks"])
        unknown = sorted(set(by_id) - set(predicates))
        if unknown:
            raise ValueError(
                f"{score_file}: assertions without predicate mapping: {', '.join(unknown)}"
            )
        row: dict[str, Any] = {key: meta.get(key) for key in KEY_COLUMNS}
        for predicate in predicate_columns:
            ids = [aid for aid, slug in predicates.items() if slug == predicate]
            row[predicate] = int(all(by_id.get(assertion_id, False) for assertion_id in ids))
        rows.append(row)
    return rows


def flatten(results_root: Path, tasks_root: Path) -> pd.DataFrame:
    rows = flatten_rows(results_root, tasks_root)
    predicates = sorted(set(load_predicates(tasks_root).values()))
    return pd.DataFrame(rows, columns=[*KEY_COLUMNS, *predicates])
