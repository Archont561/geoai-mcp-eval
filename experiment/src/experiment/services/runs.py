"""Prepare and execute experiment runs and their individual cells.

Drivers live in :mod:`experiment.drivers`; shared plumbing lives in
:mod:`experiment.harness`. These runs verify the pipeline, not study results:
outputs stay under --output-dir and retain their ``prototype`` label.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment import backends, drivers, scripted
from experiment.adapters.task_repository import discover_task_files, load_task
from experiment.domain.cache_key import CacheStats
from experiment.domain.task import Task
from experiment.domain.usage import (
    TokenCapExceededError,
    UsageAccumulator,
    aggregate_run_usage,
)
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


def parse_run_spec(  # noqa: CC102
    driver: str,
    model: str | None,
    host: str | None,
    arm: str,
    task: str,
    backend: str,
    *,
    max_cell_tokens: int | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> RunSpec:
    """Resolve the backend and validate a requested run before creating output."""
    if driver not in DRIVERS:
        raise RunSpecError(f"--driver must be one of {', '.join(DRIVERS)}")
    if max_cell_tokens is not None and max_cell_tokens < 1:
        raise RunSpecError("--max-cell-tokens must be a positive integer")
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
        max_cell_tokens=max_cell_tokens,
        backend_id=backend,
        use_cache=use_cache,
        cache_dir=cache_dir,
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
    status, error, abort_reason = "ok", None, None
    accumulator = req.usage or UsageAccumulator(max_cell_tokens=req.max_cell_tokens)
    cache_stats = req.cache_stats or CacheStats()
    active_req = replace(req, usage=accumulator, cache_stats=cache_stats)
    driver_fn = _DRIVER_DISPATCH.get((active_req.driver, active_req.arm))
    if driver_fn is None:
        status, error = "error", f"unknown driver/arm {active_req.driver}/{active_req.arm}"
        append_transcript(active_req.cell, {_K_ROLE: "harness", _K_CONTENT: f"cell error: {error}"})
    else:
        try:
            driver_fn(active_req)
        except TokenCapExceededError as exc:
            status, error, abort_reason = "aborted", str(exc), exc.reason
        except Exception as exc:
            status, error = "error", str(exc)
            append_transcript(
                active_req.cell, {_K_ROLE: "harness", _K_CONTENT: f"cell error: {exc}"}
            )
    usage_summary = accumulator.to_summary()
    append_transcript(
        active_req.cell,
        {
            _K_ROLE: "harness",
            "event": "usage_summary",
            "usage": usage_summary,
        },
    )
    score = score_cell(active_req.task_path, active_req.cell)
    meta: dict[str, Any] = {
        "run_id": active_req.run_id,
        "task": active_req.task.id,
        "arm": active_req.arm,
        "driver": active_req.driver,
        "model": model_label(active_req.driver, active_req.model),
        "model_digest": active_req.model_digest,
        "cache_hit": cache_stats.all_hit,
        "cache_hits": cache_stats.hits,
        "cache_misses": cache_stats.misses,
        "status": status,
        "error": error,
        "abort_reason": abort_reason,
        "wall_s": round(time.time() - started, 2),
        "oracle_passed": score["passed"],
        "usage": usage_summary,
        "prototype": True,
    }
    (active_req.cell / "score.json").write_text(
        json.dumps({**score, "meta": meta}, indent=JSON_INDENT, sort_keys=True), encoding=UTF8
    )
    return {**meta, "checks": score["checks"]}


def _resolve_run_digest(spec: RunSpec) -> str | None:
    if spec.driver != "ollama" or not spec.use_cache:
        return None
    profile = spec.profile or backends.fallback_profile(spec.host, spec.model)
    session = backends.build_session(profile)
    try:
        return backends.resolve_model_digest(session, profile)
    finally:
        session.close()


def _run_one_cell(  # noqa: CC102
    task_path: Path,
    task: Task,
    arm: str,
    spec: RunSpec,
    output_root: Path,
    model_digest: str | None,
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
            "model_digest": model_digest,
            "use_cache": spec.use_cache,
            "max_cell_tokens": spec.max_cell_tokens,
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
        max_cell_tokens=spec.max_cell_tokens,
        backend_id=spec.backend_id,
        model_digest=model_digest,
        use_cache=spec.use_cache,
        cache_dir=spec.cache_dir,
    )
    return run_cell(req)


def _write_manifest(  # noqa: CC102
    output_root: Path,
    spec: RunSpec,
    cells: list[dict[str, Any]],
    run_usage: dict[str, Any],
    generated_at: str,
    model_digest: str | None,
) -> dict[str, Any]:
    manifest = {
        "manifest_version": 1,
        "run_id": output_root.name,
        "prototype": True,
        "generated_at": generated_at,
        "driver": spec.driver,
        "backend_id": spec.backend_id,
        "model": model_label(spec.driver, spec.model),
        "model_digest": model_digest,
        "use_cache": spec.use_cache,
        "host": spec.host,
        "arms": list(spec.arms),
        "task_ids": sorted({cell["task"] for cell in cells}),
        "max_cell_tokens": spec.max_cell_tokens,
        "totals": {
            "cells": len(cells),
            "passed": sum(1 for c in cells if c["oracle_passed"]),
            "aborted": sum(1 for c in cells if c["status"] == "aborted"),
            "errored": sum(1 for c in cells if c["status"] == "error"),
            "cache_hits": sum(int(c.get("cache_hits") or 0) for c in cells),
            "cache_misses": sum(int(c.get("cache_misses") or 0) for c in cells),
            "usage": run_usage,
        },
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=JSON_INDENT, sort_keys=True), encoding=UTF8
    )
    return manifest


def _write_summary(
    output_root: Path,
    spec: RunSpec,
    cells: list[dict[str, Any]],
    model_digest: str | None,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat()
    run_usage = aggregate_run_usage([cell.get("usage") or {} for cell in cells])
    summary = {
        "run_id": output_root.name,
        "prototype": True,
        "driver": spec.driver,
        "backend_id": spec.backend_id,
        "model": model_label(spec.driver, spec.model),
        "model_digest": model_digest,
        "use_cache": spec.use_cache,
        "generated_at": generated_at,
        "max_cell_tokens": spec.max_cell_tokens,
        "usage": run_usage,
        "cells": cells,
        "passed": sum(1 for c in cells if c["oracle_passed"]),
        "total": len(cells),
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=JSON_INDENT, sort_keys=True), encoding=UTF8
    )
    _write_manifest(output_root, spec, cells, run_usage, generated_at, model_digest)
    return summary


def run_experiment(task_root: Path, spec: RunSpec, output_root: Path) -> dict[str, Any]:
    model_digest = _resolve_run_digest(spec)
    cells: list[dict[str, Any]] = []
    for task_path in discover_tasks(task_root):
        task = load_task(task_path)
        if spec.task_ids and task.id not in spec.task_ids:
            continue
        cells.extend(
            _run_one_cell(task_path, task, arm, spec, output_root, model_digest)
            for arm in spec.arms
        )
    return _write_summary(output_root, spec, cells, model_digest)
