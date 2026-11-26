"""Typed service DTOs for run summaries, archive overviews, and completeness reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


def _str_tuple(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(item) for item in raw)


def _opt_str(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return str(value) if value is not None else None


def _opt_int(raw: Mapping[str, Any], key: str) -> int | None:
    value = raw.get(key)
    return int(value) if value is not None else None


def _opt_bool(raw: Mapping[str, Any], key: str) -> bool | None:
    value = raw.get(key)
    return bool(value) if value is not None else None


def _opt_dict(raw: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    value = raw.get(key)
    return dict(value) if isinstance(value, Mapping) else None


class CheckView(BaseModel):
    """One oracle assertion outcome formatted for CLI tables and summaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> CheckView:
        return cls(
            assertion_id=str(raw.get("assertion_id", "")),
            passed=bool(raw.get("passed", False)),
            detail=str(raw.get("detail", "")),
        )


class CellSummary(BaseModel):
    """Typed summary of one executed or rescored trial."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    arm: str
    status: str
    oracle_passed: bool
    checks: tuple[CheckView, ...]
    wall_s: float | str = 0.0
    repetition: int = 1
    paradigm: str | None = None
    error: str | None = None
    abort_reason: str | None = None
    usage: dict[str, Any] | None = None
    cache_hits: int = 0
    cache_misses: int = 0
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.raw is not None:
            return dict(self.raw)
        payload: dict[str, Any] = {
            "task": self.task,
            "arm": self.arm,
            "repetition": self.repetition,
            "status": self.status,
            "wall_s": self.wall_s,
            "oracle_passed": self.oracle_passed,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.paradigm is not None:
            payload["paradigm"] = self.paradigm
        return payload

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> CellSummary:
        raw_checks = raw.get("checks") or ()
        checks = tuple(CheckView.from_mapping(c) for c in raw_checks if isinstance(c, Mapping))
        task = str(raw.get("task", ""))
        arm = str(raw.get("arm", ""))
        status = str(raw.get("status", "ok"))
        oracle_passed = bool(raw.get("oracle_passed", False))
        wall_s = raw.get("wall_s", "—")
        repetition = int(raw.get("repetition") or 1)
        cache_hits = int(raw.get("cache_hits") or 0)
        cache_misses = int(raw.get("cache_misses") or 0)
        return cls(
            task=task,
            arm=arm,
            status=status,
            oracle_passed=oracle_passed,
            checks=checks,
            wall_s=wall_s,
            repetition=repetition,
            paradigm=_opt_str(raw, "paradigm"),
            error=_opt_str(raw, "error"),
            abort_reason=_opt_str(raw, "abort_reason"),
            usage=_opt_dict(raw, "usage"),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            raw=dict(raw),
        )


# Preserve the historic class while exposing the study terminology.
TrialSummary = CellSummary


class RunSummary(BaseModel):
    """Typed summary of an experiment run (live, scripted, rescored, or loaded from archive)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    prototype: bool
    driver: str
    model: str
    generated_at: str
    cells: tuple[CellSummary, ...]
    passed: int
    total: int
    backend_id: str | None = None
    model_digest: str | None = None
    use_cache: bool | None = None
    max_cell_tokens: int | None = None
    usage: dict[str, Any] | None = None

    @property
    def trials(self) -> tuple[TrialSummary, ...]:
        """Trial summaries; the serialized ``cells`` field remains compatible."""
        return self.cells

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "prototype": self.prototype,
            "driver": self.driver,
            "model": self.model,
            "generated_at": self.generated_at,
            "cells": [cell.to_dict() for cell in self.cells],
            "passed": self.passed,
            "total": self.total,
        }
        if self.backend_id is not None:
            payload["backend_id"] = self.backend_id
            payload["model_digest"] = self.model_digest
            payload["use_cache"] = self.use_cache
            payload["max_cell_tokens"] = self.max_cell_tokens
            payload["usage"] = self.usage
        return payload

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RunSummary:
        raw_cells = raw.get("cells") or ()
        cells = tuple(CellSummary.from_mapping(c) for c in raw_cells if isinstance(c, Mapping))
        default_passed = sum(1 for cell in cells if cell.oracle_passed)
        passed = int(raw.get("passed", default_passed))
        total = int(raw.get("total", len(cells)))
        return cls(
            run_id=str(raw.get("run_id", "")),
            prototype=bool(raw.get("prototype", True)),
            driver=str(raw.get("driver", "")),
            model=str(raw.get("model", "—")),
            generated_at=str(raw.get("generated_at", "")),
            cells=cells,
            passed=passed,
            total=total,
            backend_id=_opt_str(raw, "backend_id"),
            model_digest=_opt_str(raw, "model_digest"),
            use_cache=_opt_bool(raw, "use_cache"),
            max_cell_tokens=_opt_int(raw, "max_cell_tokens"),
            usage=_opt_dict(raw, "usage"),
        )


class TrialOverview(BaseModel):
    """One row of an archive inspection report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str
    task_id: str
    paradigm: str
    enforcement_level: str
    repetition: int
    task_success: bool
    predicate_score: float
    silent_invalid: bool

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ArchiveOverview(BaseModel):
    """Typed summary returned by :func:`experiment.services.archive.inspect_archive`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    stage: str
    schema_version: int
    model: str | None
    model_digest: str | None
    trial_count: int
    task_success_count: int
    task_success_rate: float
    mean_predicate_score: float
    has_summary: bool
    trials: tuple[TrialOverview, ...]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CompletenessReport(BaseModel):
    """Typed harvest completeness & oracle gate table parsed from ``summary.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_cells: tuple[str, ...]
    logged_cells: tuple[str, ...]
    missing: tuple[str, ...]
    oracle_rows: tuple[tuple[str, str], ...]
    complete: bool

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> CompletenessReport | None:
        if not raw:
            return None
        oracle_raw = raw.get("oracle")
        oracle_map = oracle_raw if isinstance(oracle_raw, dict) else {}
        oracle_rows = tuple(sorted((str(k), str(v)) for k, v in oracle_map.items()))
        return cls(
            expected_cells=_str_tuple(raw.get("expected_cells")),
            logged_cells=_str_tuple(raw.get("logged_cells")),
            missing=_str_tuple(raw.get("missing")),
            oracle_rows=oracle_rows,
            complete=bool(raw.get("complete")),
        )
