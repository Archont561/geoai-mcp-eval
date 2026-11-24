"""Score experiment cells, rescore a run, and load stored summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiment import oracle
from experiment.adapters import run_store
from experiment.adapters.task_repository import discover_task_files, load_task
from experiment.harness import ARM_PREFIX, TASK_ROOT


class SummaryNotFoundError(Exception):
    """A run has no stored summary at the requested path."""


def score_cell(task_path: Path, cell: Path) -> dict[str, Any]:
    return oracle.evaluate_task(task_path, cell).to_dict()


def _rescore_cell(task_path: Path, cell: Path) -> dict[str, Any]:
    task_id = cell.parent.name
    arm = cell.name.removeprefix(ARM_PREFIX)
    report = score_cell(task_path, cell)
    return {
        **report,
        "task": task_id,
        "arm": arm,
        "status": "rescored",
        "wall_s": "—",
        "oracle_passed": report["passed"],
    }


def rescore_run(run_dir: Path, task_root: Path = TASK_ROOT) -> dict[str, Any] | None:
    """Build a display summary, or return None when no known cells exist."""
    task_by_id = {load_task(path).id: path for path in discover_task_files(task_root)}
    cells = [
        _rescore_cell(task_by_id[cell.parent.name], cell)
        for cell in run_store.discover_cell_dirs(run_dir, ARM_PREFIX)
        if cell.parent.name in task_by_id
    ]
    if not cells:
        return None
    return {
        "run_id": run_dir.name,
        "prototype": True,
        "driver": "rescore",
        "model": "—",
        "generated_at": "",
        "cells": cells,
        "passed": sum(1 for cell in cells if cell["oracle_passed"]),
        "total": len(cells),
    }


def load_summary(run_dir: Path) -> Any:
    """Read the existing summary, distinguishing a missing file from bad JSON."""
    path = run_dir / "summary.json"
    if not path.is_file():
        raise SummaryNotFoundError(path)
    return run_store.read_json(path)
