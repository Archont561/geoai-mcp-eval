"""Prototype cell runner for the experiment typer app.

Runs one (task, arm) cell end-to-end and scores the artifact with the committed
oracle. Drivers live in :mod:`experiment.drivers`; shared plumbing in
:mod:`experiment.harness`. Nothing here is a study result; outputs live under
--output-dir (gitignored results/ by default) and are labeled ``prototype``.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from experiment import drivers, oracle, scripted
from experiment.harness import (
    _K_CONTENT,
    _K_ROLE,
    JSON_INDENT,
    UTF8,
    CellRequest,
    RunSpec,
    append_transcript,
    cell_dir,
    model_label,
)

__all__ = [
    "CellRequest",
    "RunSpec",
    "discover_tasks",
    "load_task",
    "score_cell",
    "run_cell",
    "run_experiment",
]


def discover_tasks(root: Path) -> list[Path]:
    """Return the committed task YAML paths (excludes schema-v1.json)."""
    return sorted(p for p in root.glob("*.yaml") if p.is_file())


def load_task(path: Path) -> dict[str, Any]:
    task = yaml.safe_load(path.read_text(encoding=UTF8))
    if not isinstance(task, dict) or "id" not in task:
        raise ValueError(f"{path} is not a task YAML")
    return task


def score_cell(task_path: Path, cell: Path) -> dict[str, Any]:
    verdict = oracle.evaluate_task(task_path, cell)
    return verdict.to_dict()


_DRIVER_DISPATCH = {
    ("scripted", "A"): scripted.scripted_arm_a,
    ("scripted", "B"): scripted.scripted_arm_b,
    ("ollama", "A"): drivers.ollama_arm_a,
    ("ollama", "B"): drivers.ollama_arm_b,
}


def run_cell(req: CellRequest) -> dict[str, Any]:
    started = time.time()
    status, error = "ok", None
    driver_fn = _DRIVER_DISPATCH.get((req.driver, req.arm))
    if driver_fn is None:
        status, error = "error", f"unknown driver/arm {req.driver}/{req.arm}"
        append_transcript(req.cell, {_K_ROLE: "harness", _K_CONTENT: f"cell error: {error}"})
    else:
        try:
            driver_fn(req)
        except Exception as exc:
            status, error = "error", str(exc)
            append_transcript(req.cell, {_K_ROLE: "harness", _K_CONTENT: f"cell error: {exc}"})
    score = score_cell(req.task_path, req.cell)
    meta = {
        "run_id": req.run_id,
        "task": req.task["id"],
        "arm": req.arm,
        "driver": req.driver,
        "model": model_label(req.driver, req.model),
        "status": status,
        "error": error,
        "wall_s": round(time.time() - started, 2),
        "oracle_passed": score["passed"],
        "prototype": True,
    }
    (req.cell / "score.json").write_text(
        json.dumps({**score, "meta": meta}, indent=JSON_INDENT, sort_keys=True), encoding=UTF8
    )
    return {**meta, "checks": score["checks"]}


def _run_one_cell(
    task_path: Path, task: dict[str, Any], arm: str, spec: RunSpec, output_root: Path
) -> dict[str, Any]:
    cell = cell_dir(output_root, task["id"], arm)
    append_transcript(
        cell,
        {
            _K_ROLE: "meta",
            "task": task["id"],
            "arm": arm,
            "driver": spec.driver,
            "model": model_label(spec.driver, spec.model),
            "prototype": True,
            "required_traps": task.get("required_traps", []),
        },
    )
    req = CellRequest(
        task_path=task_path,
        task=task,
        arm=arm,
        driver=spec.driver,
        cell=cell,
        model=spec.model,
        host=spec.host,
        run_id=output_root.name,
        profile=spec.profile,
    )
    return run_cell(req)


def _write_summary(output_root: Path, spec: RunSpec, cells: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "run_id": output_root.name,
        "prototype": True,
        "driver": spec.driver,
        "model": model_label(spec.driver, spec.model),
        "generated_at": datetime.now(UTC).isoformat(),
        "cells": cells,
        "passed": sum(1 for c in cells if c["oracle_passed"]),
        "total": len(cells),
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=JSON_INDENT, sort_keys=True), encoding=UTF8
    )
    return summary


def run_experiment(task_root: Path, spec: RunSpec, output_root: Path) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for task_path in discover_tasks(task_root):
        task = load_task(task_path)
        if spec.task_ids and task["id"] not in spec.task_ids:
            continue
        cells.extend(_run_one_cell(task_path, task, arm, spec, output_root) for arm in spec.arms)
    return _write_summary(output_root, spec, cells)
