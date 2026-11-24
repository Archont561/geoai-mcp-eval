"""Prepare and execute experiment runs and their individual cells.

Drivers live in :mod:`experiment.drivers`; shared plumbing lives in
:mod:`experiment.harness`. These runs verify the pipeline, not study results:
outputs stay under --output-dir and retain their ``prototype`` label.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment import backends, drivers, scripted
from experiment.adapters.task_repository import discover_task_files, load_task
from experiment.domain.task import Task
from experiment.harness import (
    _K_CONTENT,
    _K_ROLE,
    DRIVERS,
    JSON_INDENT,
    UTF8,
    CellRequest,
    RunSpec,
    append_transcript,
    cell_dir,
    model_label,
)
from experiment.services.scoring import score_cell


class RunSpecError(ValueError):
    """A run cannot start with the requested driver, arm, or backend."""


def _parse_arms(raw: str) -> tuple[str, ...]:
    mapping = {"both": ("A", "B"), "a": ("A",), "b": ("B",)}
    key = raw.strip().lower()
    if key not in mapping:
        raise RunSpecError(f"--arm must be one of both|A|B, got {raw!r}")
    return mapping[key]


def _parse_tasks(raw: str) -> tuple[str, ...] | None:
    if raw.strip().lower() == "all":
        return None
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_run_spec(
    driver: str, model: str | None, host: str | None, arm: str, task: str, backend: str
) -> RunSpec:
    """Resolve the backend and validate a requested run before creating output."""
    if driver not in DRIVERS:
        raise RunSpecError(f"--driver must be one of {', '.join(DRIVERS)}")
    try:
        profile = backends.resolve_profile(backend, host=host, model=model)
        if driver == "ollama":
            backends.require_api_key(profile)
    except backends.BackendError as exc:
        raise RunSpecError(str(exc)) from exc
    return RunSpec(
        driver=driver,
        model=profile.model,
        host=str(profile.base_url),
        arms=_parse_arms(arm),
        task_ids=_parse_tasks(task),
        profile=profile,
    )


def discover_tasks(root: Path) -> list[Path]:
    """The committed task YAML paths (excludes schema-v1.json)."""
    return discover_task_files(root)


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
        "task": req.task.id,
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
    task_path: Path, task: Task, arm: str, spec: RunSpec, output_root: Path
) -> dict[str, Any]:
    cell = cell_dir(output_root, task.id, arm)
    append_transcript(
        cell,
        {
            _K_ROLE: "meta",
            "task": task.id,
            "arm": arm,
            "driver": spec.driver,
            "model": model_label(spec.driver, spec.model),
            "prototype": True,
            "required_traps": list(task.required_traps),
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
        if spec.task_ids and task.id not in spec.task_ids:
            continue
        cells.extend(_run_one_cell(task_path, task, arm, spec, output_root) for arm in spec.arms)
    return _write_summary(output_root, spec, cells)
