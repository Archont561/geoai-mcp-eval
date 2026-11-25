"""Prepare and execute experiment runs and their individual cells.

Runners live in :mod:`experiment.services.runners`; cell I/O plumbing lives in
:mod:`experiment.adapters.harness_io`. These runs verify the pipeline, not study
results: outputs stay under --output-dir and retain their ``prototype`` label.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from experiment.adapters import backends, run_store
from experiment.adapters.harness_io import (
    TASK_ROOT,
    append_transcript,
    cell_dir,
    model_label,
    resolve_output_dir,
)
from experiment.adapters.task_repository import discover_task_files, load_task
from experiment.domain.cache_key import CacheStats
from experiment.domain.run import EnforcementLevel, TrialKey, arm_to_paradigm
from experiment.domain.task import Task
from experiment.domain.usage import (
    TokenCapExceededError,
    UsageAccumulator,
    aggregate_run_usage,
)
from experiment.services.measurement import TrialMeasurementOptions, measure_trial
from experiment.services.reports import CellSummary, RunSummary
from experiment.services.run_spec import RunSpecError, RunSpecInput, parse_enforce, parse_run_spec
from experiment.services.runners import ollama as drivers
from experiment.services.runners import scripted
from experiment.services.runners.ports import CellRequest, RunSpec
from experiment.services.scoring import score_cell

__all__ = [
    "TASK_ROOT",
    "CellRequest",
    "RunSpec",
    "RunSpecError",
    "RunSpecInput",
    "RunSummary",
    "discover_tasks",
    "model_label",
    "parse_run_spec",
    "resolve_output_dir",
    "run_cell",
    "run_experiment",
]


class _RunContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: RunSpec
    output_root: Path
    model_digest: str | None


class _CellOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    error: str | None
    abort_reason: str | None
    wall_s: float


def discover_tasks(root: Path) -> list[Path]:
    """The committed task YAML paths (excludes schema-v1.json)."""
    return discover_task_files(root)


_DRIVER_DISPATCH = {
    ("scripted", "A"): scripted.scripted_arm_a,
    ("scripted", "B"): scripted.scripted_arm_b,
    ("ollama", "A"): drivers.ollama_arm_a,
    ("ollama", "B"): drivers.ollama_arm_b,
}


def _execute_driver(active_req: CellRequest) -> _CellOutcome:
    started = time.time()
    driver_fn = _DRIVER_DISPATCH.get((active_req.driver, active_req.arm))
    if driver_fn is None:
        error = f"unknown driver/arm {active_req.driver}/{active_req.arm}"
        append_transcript(active_req.cell, {"role": "harness", "content": f"cell error: {error}"})
        return _CellOutcome(
            status="error", error=error, abort_reason=None, wall_s=round(time.time() - started, 2)
        )
    try:
        driver_fn(active_req)
        return _CellOutcome(
            status="ok", error=None, abort_reason=None, wall_s=round(time.time() - started, 2)
        )
    except TokenCapExceededError as exc:
        return _CellOutcome(
            status="aborted",
            error=str(exc),
            abort_reason=exc.reason,
            wall_s=round(time.time() - started, 2),
        )
    except Exception as exc:
        append_transcript(active_req.cell, {"role": "harness", "content": f"cell error: {exc}"})
        return _CellOutcome(
            status="error",
            error=str(exc),
            abort_reason=None,
            wall_s=round(time.time() - started, 2),
        )


def _build_cell_meta(
    active_req: CellRequest,
    outcome: _CellOutcome,
    score: dict[str, Any],
    usage_summary: dict[str, Any],
) -> dict[str, Any]:
    cache_stats = active_req.cache_stats or CacheStats()
    return {
        "run_id": active_req.run_id,
        "task": active_req.task.id,
        "arm": active_req.arm,
        "repetition": active_req.repetition,
        "driver": active_req.driver,
        "model": model_label(active_req.driver, active_req.model),
        "model_digest": active_req.model_digest,
        "cache_hit": cache_stats.all_hit,
        "cache_hits": cache_stats.hits,
        "cache_misses": cache_stats.misses,
        "status": outcome.status,
        "error": outcome.error,
        "abort_reason": outcome.abort_reason,
        "wall_s": outcome.wall_s,
        "oracle_passed": score["passed"],
        "usage": usage_summary,
        "prototype": True,
    }


def _trial_key_for_cell(req: CellRequest) -> TrialKey:
    paradigm = arm_to_paradigm(req.arm)
    enforcement: EnforcementLevel = (
        parse_enforce(req.enforce) if paradigm == "typed_mcp" else "none"
    )
    return TrialKey(
        task_id=req.task.id,
        paradigm=paradigm,
        enforcement_level=enforcement,
        repetition=req.repetition,
    )


def run_cell(req: CellRequest) -> dict[str, Any]:
    accumulator = req.usage or UsageAccumulator(max_cell_tokens=req.max_cell_tokens)
    active_req = req.model_copy(
        update={"usage": accumulator, "cache_stats": req.cache_stats or CacheStats()}
    )
    outcome = _execute_driver(active_req)
    usage_summary = accumulator.to_summary()
    append_transcript(
        active_req.cell,
        {"role": "harness", "event": "usage_summary", "usage": usage_summary},
    )
    score = score_cell(active_req.task_path, active_req.cell)
    meta = _build_cell_meta(active_req, outcome, score, usage_summary)
    measurement = measure_trial(
        active_req.task_path,
        active_req.cell,
        key=_trial_key_for_cell(active_req),
        options=TrialMeasurementOptions(
            wall_seconds=outcome.wall_s,
            token_usage=accumulator.to_token_usage(),
        ),
    )
    run_store.write_json(
        active_req.cell / "score.json",
        {**score, "meta": meta, "measurement": measurement.model_dump(mode="json")},
    )
    return {**meta, "checks": score["checks"], "measurement": measurement.model_dump(mode="json")}


def _resolve_run_digest(spec: RunSpec) -> str | None:
    if spec.driver != "ollama" or not spec.use_cache:
        return None
    profile = spec.profile or backends.fallback_profile(spec.host, spec.model)
    session = backends.build_session(profile)
    try:
        return backends.resolve_model_digest(session, profile)
    finally:
        session.close()


def _cell_meta_record(task: Task, arm: str, repetition: int, ctx: _RunContext) -> dict[str, Any]:
    return {
        "role": "meta",
        "task": task.id,
        "arm": arm,
        "repetition": repetition,
        "driver": ctx.spec.driver,
        "model": model_label(ctx.spec.driver, ctx.spec.model),
        "model_digest": ctx.model_digest,
        "use_cache": ctx.spec.use_cache,
        "max_cell_tokens": ctx.spec.max_cell_tokens,
        "prototype": True,
        "required_traps": list(task.required_traps),
    }


def _run_one_cell(
    task_path: Path, task: Task, arm: str, repetition: int, ctx: _RunContext
) -> dict[str, Any]:
    cell = cell_dir(ctx.output_root, task.id, arm, repetition)
    append_transcript(cell, _cell_meta_record(task, arm, repetition, ctx))
    req = CellRequest(
        task_path=task_path,
        task=task,
        arm=arm,
        driver=ctx.spec.driver,
        cell=cell,
        model=ctx.spec.model,
        host=ctx.spec.host,
        run_id=ctx.output_root.name,
        profile=ctx.spec.profile,
        max_cell_tokens=ctx.spec.max_cell_tokens,
        backend_id=ctx.spec.backend_id,
        model_digest=ctx.model_digest,
        use_cache=ctx.spec.use_cache,
        cache_dir=ctx.spec.cache_dir,
        enforce=ctx.spec.enforce,
        repetition=repetition,
    )
    return run_cell(req)


def _run_totals(cells: list[dict[str, Any]], run_usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "cells": len(cells),
        "passed": sum(1 for c in cells if c["oracle_passed"]),
        "aborted": sum(1 for c in cells if c["status"] == "aborted"),
        "errored": sum(1 for c in cells if c["status"] == "error"),
        "cache_hits": sum(int(c.get("cache_hits") or 0) for c in cells),
        "cache_misses": sum(int(c.get("cache_misses") or 0) for c in cells),
        "usage": run_usage,
    }


def _write_manifest(
    ctx: _RunContext,
    cells: list[dict[str, Any]],
    run_usage: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    manifest = {
        "manifest_version": 1,
        "run_id": ctx.output_root.name,
        "prototype": True,
        "generated_at": generated_at,
        "driver": ctx.spec.driver,
        "backend_id": ctx.spec.backend_id,
        "model": model_label(ctx.spec.driver, ctx.spec.model),
        "model_digest": ctx.model_digest,
        "use_cache": ctx.spec.use_cache,
        "host": ctx.spec.host,
        "arms": list(ctx.spec.arms),
        "task_ids": sorted({cell["task"] for cell in cells}),
        "max_cell_tokens": ctx.spec.max_cell_tokens,
        "totals": _run_totals(cells, run_usage),
    }
    run_store.write_json(ctx.output_root / "manifest.json", manifest)
    return manifest


def _write_summary(ctx: _RunContext, cells: list[dict[str, Any]]) -> RunSummary:
    generated_at = datetime.now(UTC).isoformat()
    run_usage = aggregate_run_usage([cell.get("usage") or {} for cell in cells])
    typed_cells = tuple(CellSummary.from_mapping(cell) for cell in cells)
    summary = RunSummary(
        run_id=ctx.output_root.name,
        prototype=True,
        driver=ctx.spec.driver,
        backend_id=ctx.spec.backend_id,
        model=model_label(ctx.spec.driver, ctx.spec.model),
        model_digest=ctx.model_digest,
        use_cache=ctx.spec.use_cache,
        generated_at=generated_at,
        max_cell_tokens=ctx.spec.max_cell_tokens,
        usage=run_usage,
        cells=typed_cells,
        passed=sum(1 for cell in typed_cells if cell.oracle_passed),
        total=len(typed_cells),
    )
    run_store.write_json(ctx.output_root / "summary.json", summary.to_dict())
    _write_manifest(ctx, cells, run_usage, generated_at)
    return summary


def run_experiment(task_root: Path, spec: RunSpec, output_root: Path) -> RunSummary:
    ctx = _RunContext(spec=spec, output_root=output_root, model_digest=_resolve_run_digest(spec))
    cells: list[dict[str, Any]] = []
    for task_path in discover_tasks(task_root):
        task = load_task(task_path)
        if spec.task_ids and task.id not in spec.task_ids:
            continue
        cells.extend(
            _run_one_cell(task_path, task, arm, rep, ctx)
            for arm in spec.arms
            for rep in range(1, spec.repetitions + 1)
        )
    return _write_summary(ctx, cells)
