"""Score experiment trials, rescore runs/archives, run determinism gate, and load summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiment import oracle
from experiment.adapters import run_store
from experiment.adapters.harness_io import TASK_ROOT
from experiment.adapters.run_archive import RunArchive
from experiment.adapters.task_repository import discover_task_files, load_task
from experiment.domain.run import TrialMeasurement
from experiment.oracle._base import DeterminismReport
from experiment.services.reports import CellSummary, CheckView, RunSummary


class SummaryNotFoundError(Exception):
    """A run has no stored summary at the requested path."""


def score_cell(task_path: Path, cell: Path) -> dict[str, Any]:
    return oracle.evaluate_task(task_path, cell).to_dict()


def run_determinism_gate(task_path: Path, artifacts_dir: Path) -> DeterminismReport:
    """Run the task oracle three times against fixed artifacts."""
    return oracle.run_determinism_gate(task_path, artifacts_dir)


def _rescore_cell(task_path: Path, cell: run_store.CellDir) -> CellSummary:
    report = score_cell(task_path, cell.path)
    checks = tuple(CheckView.from_mapping(c) for c in report.get("checks", ()))
    return CellSummary(
        task=cell.task_id,
        arm=cell.arm,
        repetition=cell.repetition,
        status="rescored",
        oracle_passed=bool(report["passed"]),
        checks=checks,
        wall_s="—",
        raw={
            **report,
            "task": cell.task_id,
            "arm": cell.arm,
            "repetition": cell.repetition,
            "status": "rescored",
            "wall_s": "—",
            "oracle_passed": report["passed"],
        },
    )


def _archive_cell_row(measurement: TrialMeasurement) -> CellSummary:
    arm = "A" if measurement.key.paradigm == "typed_mcp" else "B"
    checks = tuple(
        CheckView(assertion_id=a.assertion_id, passed=a.passed, detail=a.detail)
        for a in measurement.assertions
    )
    passed = bool(measurement.outcomes.task_success)
    wall = round(measurement.economics.wall_seconds or 0.0, 2)
    return CellSummary(
        task=measurement.key.task_id,
        arm=arm,
        paradigm=measurement.key.paradigm,
        status="ok" if passed else "error",
        wall_s=wall,
        oracle_passed=passed,
        checks=checks,
    )


def _summary_from_archive(archive_path: Path) -> RunSummary:
    with RunArchive.open(archive_path) as archive:
        run = archive.run
        cells = tuple(_archive_cell_row(m) for m in run.measurements.values())
        model_pin = run.provenance.model
        driver = (model_pin.backend_id if model_pin else None) or "archive"
        model = (model_pin.tag if model_pin else None) or "—"
        passed = sum(1 for cell in cells if cell.oracle_passed)
        return RunSummary(
            run_id=run.run_id,
            prototype=run.stage != "study",
            driver=driver,
            model=model,
            generated_at=run.created_at.isoformat(),
            cells=cells,
            passed=passed,
            total=len(cells),
        )


def rescore_run(run_dir: Path, task_root: Path | None = None) -> RunSummary | None:
    """Build a display summary from a run directory or zip archive, or return None."""
    if run_store.is_file(run_dir) and run_dir.suffix == ".zip":
        return _summary_from_archive(run_dir)
    suite_root = task_root if task_root is not None else TASK_ROOT
    task_by_id = {load_task(path).id: path for path in discover_task_files(suite_root)}
    cells = tuple(
        _rescore_cell(task_by_id[cell.task_id], cell)
        for cell in run_store.discover_cells(run_dir)
        if cell.task_id in task_by_id
    )
    if not cells:
        return None
    return RunSummary(
        run_id=run_dir.name,
        prototype=True,
        driver="rescore",
        model="—",
        generated_at="",
        cells=cells,
        passed=sum(1 for cell in cells if cell.oracle_passed),
        total=len(cells),
    )


def load_summary(run_dir: Path) -> RunSummary:
    """Read an existing summary from a directory or ``RunArchive`` zip."""
    if run_store.is_file(run_dir) and run_dir.suffix == ".zip":
        return _summary_from_archive(run_dir)
    path = run_dir / "summary.json"
    if not run_store.is_file(path):
        raise SummaryNotFoundError(path)
    raw = run_store.read_json_mapping(path)
    if raw is None:
        raise SummaryNotFoundError(path)
    return RunSummary.from_mapping(raw)
