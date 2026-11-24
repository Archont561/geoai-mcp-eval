"""Score experiment cells, rescore runs/archives, run determinism gate, and load summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiment import oracle
from experiment.adapters import run_store
from experiment.adapters.harness_io import ARM_PREFIX, TASK_ROOT
from experiment.adapters.run_archive import RunArchive
from experiment.adapters.task_repository import discover_task_files, load_task


class SummaryNotFoundError(Exception):
    """A run has no stored summary at the requested path."""


def score_cell(task_path: Path, cell: Path) -> dict[str, Any]:
    return oracle.evaluate_task(task_path, cell).to_dict()


def run_determinism_gate(task_path: Path, artifacts_dir: Path) -> Any:
    """Run the task oracle three times against fixed artifacts."""
    return oracle.run_determinism_gate(task_path, artifacts_dir)


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


def _archive_cell_row(measurement: Any) -> dict[str, Any]:
    arm = "A" if measurement.key.paradigm == "typed_mcp" else "B"
    checks = [
        {"assertion_id": a.assertion_id, "passed": a.passed, "detail": a.detail}
        for a in measurement.assertions
    ]
    passed = bool(measurement.outcomes.task_success)
    wall = measurement.economics.wall_seconds or 0.0
    return {
        "task": measurement.key.task_id,
        "arm": arm,
        "paradigm": measurement.key.paradigm,
        "status": "ok" if passed else "error",
        "wall_s": round(wall, 2),
        "oracle_passed": passed,
        "checks": checks,
    }


def _summary_from_archive(archive_path: Path) -> dict[str, Any]:
    with RunArchive.open(archive_path) as archive:
        run = archive.run
        cells = [_archive_cell_row(m) for m in run.measurements.values()]
        model_pin = run.provenance.model
        return {
            "run_id": run.run_id,
            "prototype": run.stage != "study",
            "driver": (model_pin.backend_id if model_pin else None) or "archive",
            "model": (model_pin.tag if model_pin else None) or "—",
            "generated_at": run.created_at.isoformat(),
            "cells": cells,
            "passed": sum(1 for cell in cells if cell["oracle_passed"]),
            "total": len(cells),
        }


def rescore_run(run_dir: Path, task_root: Path | None = None) -> dict[str, Any] | None:
    """Build a display summary from a run directory or zip archive, or return None."""
    if run_dir.is_file() and run_dir.suffix == ".zip":
        return _summary_from_archive(run_dir)
    suite_root = task_root if task_root is not None else TASK_ROOT
    task_by_id = {load_task(path).id: path for path in discover_task_files(suite_root)}
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
    """Read an existing summary from a directory or ``RunArchive`` zip."""
    if run_dir.is_file() and run_dir.suffix == ".zip":
        return _summary_from_archive(run_dir)
    path = run_dir / "summary.json"
    if not path.is_file():
        raise SummaryNotFoundError(path)
    return run_store.read_json(path)
