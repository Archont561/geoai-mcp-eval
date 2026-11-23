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
import yaml

KEY_COLUMNS = ("run_id", "task", "arm", "driver", "model")


def load_predicates(tasks_root: Path) -> dict[str, str]:
    """Map assertion id -> predicate slug across the task suite."""
    mapping: dict[str, str] = {}
    for path in sorted(tasks_root.glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(task, dict):
            continue
        assertions = task.get("oracle", {}).get("assertions", [])
        if not isinstance(assertions, list):
            continue
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id, predicate = assertion.get("id"), assertion.get("predicate")
            if isinstance(assertion_id, str) and isinstance(predicate, str):
                mapping[assertion_id] = predicate
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
