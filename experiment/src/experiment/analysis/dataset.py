"""DataFrame projections and lazy trial inspection over ``RunArchive`` / ``ExperimentRun``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from experiment.adapters.run_archive import LazyTrialHandle, RunArchive
from experiment.analysis.predicates import load_predicates
from experiment.domain.run import ExperimentRun, TrialKey, TrialMeasurement, TrialRecord

_COL_RUN_ID = "run_id"
_COL_TRIAL_ID = "trial_id"
_COL_TASK_ID = "task_id"
_COL_PARADIGM = "paradigm"
_COL_ENFORCEMENT = "enforcement_level"
_COL_REPETITION = "repetition"

_GROUP_KEYS: list[str] = [_COL_TASK_ID, _COL_PARADIGM, _COL_ENFORCEMENT]

MEASUREMENT_COLUMNS: tuple[str, ...] = (
    _COL_RUN_ID,
    _COL_TRIAL_ID,
    _COL_TASK_ID,
    _COL_PARADIGM,
    _COL_ENFORCEMENT,
    _COL_REPETITION,
    "status",
    "driver",
    "model_tag",
    "model_digest",
    "task_success",
    "predicate_score",
    "silent_invalid",
    "wall_seconds",
    "llm_calls",
    "tool_calls",
    "repair_turns",
    "schema_violations",
    "human_steps",
    "input_tokens",
    "output_tokens",
    "total_tokens",
)

PREDICATE_KEY_COLUMNS: tuple[str, ...] = (
    _COL_RUN_ID,
    _COL_TRIAL_ID,
    _COL_TASK_ID,
    _COL_PARADIGM,
    _COL_ENFORCEMENT,
    _COL_REPETITION,
)

CELL_SUMMARY_COLUMNS: tuple[str, ...] = (
    _COL_TASK_ID,
    _COL_PARADIGM,
    _COL_ENFORCEMENT,
    "n_trials",
    "task_success_rate",
    "predicate_score_mean",
    "predicate_score_median",
    "pass_at_k",
    "silent_invalid_rate",
    "wall_seconds_mean",
)

ASSERTION_COLUMNS: tuple[str, ...] = (
    _COL_RUN_ID,
    _COL_TRIAL_ID,
    _COL_TASK_ID,
    _COL_PARADIGM,
    _COL_ENFORCEMENT,
    _COL_REPETITION,
    "assertion_id",
    "predicate",
    "tier",
    "passed",
    "detail",
)


def _key_fields(run_id: str, m: TrialMeasurement) -> dict[str, Any]:
    return {
        _COL_RUN_ID: run_id,
        _COL_TRIAL_ID: m.trial_id,
        _COL_TASK_ID: m.key.task_id,
        _COL_PARADIGM: m.key.paradigm,
        _COL_ENFORCEMENT: m.key.enforcement_level,
        _COL_REPETITION: m.key.repetition,
    }


def _measurement_row(
    run_id: str,
    trial: TrialRecord | None,
    m: TrialMeasurement,
) -> dict[str, Any]:
    econ = m.economics
    tokens = econ.tokens
    return {
        **_key_fields(run_id, m),
        "status": trial.status if trial is not None else "ok",
        "driver": trial.driver if trial is not None else None,
        "model_tag": trial.model_tag if trial is not None else None,
        "model_digest": trial.model_digest if trial is not None else None,
        "task_success": int(m.outcomes.task_success),
        "predicate_score": float(m.outcomes.predicate_score),
        "silent_invalid": bool(m.outcomes.silent_invalid),
        "wall_seconds": econ.wall_seconds,
        "llm_calls": econ.llm_calls,
        "tool_calls": econ.tool_calls,
        "repair_turns": econ.repair_turns,
        "schema_violations": econ.schema_violations,
        "human_steps": econ.human_steps,
        "input_tokens": tokens.input_tokens,
        "output_tokens": tokens.output_tokens,
        "total_tokens": tokens.total_tokens,
    }


def _predicate_row(
    run_id: str,
    m: TrialMeasurement,
    predicates: dict[str, str],
    columns: list[str],
) -> dict[str, Any]:
    by_id = {a.assertion_id: bool(a.passed) for a in m.assertions}
    unknown = sorted(set(by_id) - set(predicates))
    if unknown:
        raise ValueError(
            f"{m.trial_id}: assertions without predicate mapping: {', '.join(unknown)}"
        )
    row = _key_fields(run_id, m)
    inverse = {slug: aid for aid, slug in predicates.items()}
    for slug in columns:
        row[slug] = int(by_id.get(inverse[slug], False))
    return row


def _assertion_rows(
    run_id: str,
    m: TrialMeasurement,
    predicates: dict[str, str],
) -> list[dict[str, Any]]:
    base = _key_fields(run_id, m)
    rows: list[dict[str, Any]] = []
    for item in m.assertions:
        if item.assertion_id not in predicates:
            raise ValueError(
                f"{m.trial_id}: assertion {item.assertion_id!r} has no predicate mapping"
            )
        rows.append(
            {
                **base,
                "assertion_id": item.assertion_id,
                "predicate": predicates[item.assertion_id],
                "tier": item.tier,
                "passed": bool(item.passed),
                "detail": item.detail,
            }
        )
    return rows


def _aggregate_cell_group(group_key: tuple[Any, ...], frame: pd.DataFrame) -> dict[str, Any]:
    task_id, paradigm, enforcement = (str(part) for part in group_key)
    n_trials = int(len(frame))
    tsr = float(frame["task_success"].mean())
    wall = frame["wall_seconds"].dropna()
    return {
        _COL_TASK_ID: task_id,
        _COL_PARADIGM: paradigm,
        _COL_ENFORCEMENT: enforcement,
        "n_trials": n_trials,
        "task_success_rate": tsr,
        "predicate_score_mean": float(frame["predicate_score"].mean()),
        "predicate_score_median": float(frame["predicate_score"].median()),
        "pass_at_k": bool(n_trials > 0 and tsr == 1.0),
        "silent_invalid_rate": float(frame["silent_invalid"].mean()),
        "wall_seconds_mean": float(wall.mean()) if len(wall) > 0 else None,
    }


class RunDataset:
    """Notebook-oriented dataset over a validated ``ExperimentRun`` / ``RunArchive``."""

    def __init__(
        self,
        run: ExperimentRun,
        *,
        archive: RunArchive | None = None,
        owns_archive: bool = False,
    ) -> None:
        self._run = run
        self._archive = archive
        self._owns_archive = owns_archive

    @classmethod
    def from_zip(cls, path: Path | str) -> RunDataset:
        """Open a single ``experiment-run-*.zip`` archive as a lazy ``RunDataset``."""
        archive = RunArchive.open(Path(path))
        return cls(archive.run, archive=archive, owns_archive=True)

    @classmethod
    def from_archive(cls, archive: RunArchive) -> RunDataset:
        """Wrap an already-open ``RunArchive`` without taking ownership of closing it."""
        return cls(archive.run, archive=archive, owns_archive=False)

    @classmethod
    def from_run(cls, run: ExperimentRun) -> RunDataset:
        """Build an in-memory ``RunDataset`` from a validated ``ExperimentRun`` DTO."""
        return cls(run, archive=None, owns_archive=False)

    @property
    def run(self) -> ExperimentRun:
        return self._run

    def close(self) -> None:
        if self._owns_archive and self._archive is not None:
            self._archive.close()
            self._archive = None

    def __enter__(self) -> RunDataset:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def trial(self, key: str | TrialKey) -> LazyTrialHandle:
        """Return a lazy SHA-256-verified trial handle for drilling into transcripts/artifacts."""
        if self._archive is None:
            raise RuntimeError("lazy trial inspection requires a zip-backed RunDataset")
        trial_id = key.slug if isinstance(key, TrialKey) else key
        return self._archive.trial(trial_id)

    def _ordered_measurements(self) -> list[TrialMeasurement]:
        return [self._run.measurements[tid] for tid in sorted(self._run.measurements)]

    def measurements_df(self) -> pd.DataFrame:
        """One row per measured trial with outcomes, economics, and provenance."""
        rows = [
            _measurement_row(self._run.run_id, self._run.trials.get(m.trial_id), m)
            for m in self._ordered_measurements()
        ]
        return pd.DataFrame(rows, columns=list(MEASUREMENT_COLUMNS))

    def predicates_df(self, tasks_root: Path | None = None) -> pd.DataFrame:
        """Flat 0/1 predicate matrix preserving strict cross-task zero semantics (no NaN)."""
        predicates = load_predicates(tasks_root)
        predicate_cols = sorted(set(predicates.values()))
        rows = [
            _predicate_row(self._run.run_id, m, predicates, predicate_cols)
            for m in self._ordered_measurements()
        ]
        return pd.DataFrame(rows, columns=[*PREDICATE_KEY_COLUMNS, *predicate_cols])

    def cell_summary_df(self) -> pd.DataFrame:
        """Per ``task_id x paradigm x enforcement_level`` aggregate summary table."""
        df = self.measurements_df()
        if df.empty:
            return pd.DataFrame(columns=list(CELL_SUMMARY_COLUMNS))
        grouped = df.groupby(_GROUP_KEYS, sort=True)
        rows = [_aggregate_cell_group(key, group) for key, group in grouped]
        return pd.DataFrame(rows, columns=list(CELL_SUMMARY_COLUMNS))

    def assertions_df(self, tasks_root: Path | None = None) -> pd.DataFrame:
        """Long-form per-assertion verdicts with predicate slug and assertion tier."""
        predicates = load_predicates(tasks_root)
        rows: list[dict[str, Any]] = []
        for m in self._ordered_measurements():
            rows.extend(_assertion_rows(self._run.run_id, m, predicates))
        return pd.DataFrame(rows, columns=list(ASSERTION_COLUMNS))
