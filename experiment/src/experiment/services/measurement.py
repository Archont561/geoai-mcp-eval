"""TrialMeasurement DTO assembly for agent trials and human reference sessions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiment import oracle
from experiment.adapters import run_store
from experiment.adapters.task_repository import load_task
from experiment.domain.run import (
    AssertionResult,
    CostAndProcessMetrics,
    DeterminismAudit,
    TokenUsage,
    TrialKey,
    TrialMeasurement,
    extract_transcript_metrics,
    infer_assertion_tier,
)
from experiment.domain.task import Task
from experiment.oracle._base import DeterminismReport


@dataclass(frozen=True)
class TrialMeasurementOptions:
    """Optional provenance/economics context passed when measuring one trial."""

    wall_seconds: float | None = None
    token_usage: TokenUsage | None = None
    determinism: DeterminismReport | None = None


def determinism_report_to_audit(report: DeterminismReport) -> DeterminismAudit:
    """Convert an oracle DeterminismReport into a typed DeterminismAudit DTO."""
    return DeterminismAudit(
        passes_required=report.required_runs,
        passes_executed=len(report.run_results),
        consistent=report.consistent,
        passed=report.passed,
        issues=list(report.issues),
    )


def _read_transcript_records(cell_dir: Path) -> list[dict[str, Any]]:
    path = cell_dir / "transcript.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in run_store.read_text(path).splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _deliverable_readable(task: Task, cell_dir: Path) -> bool:
    outputs = sorted(
        {
            str(assertion.get("output"))
            for assertion in task.oracle.assertions
            if assertion.get("output")
        }
    )
    if not outputs:
        return False
    return all(run_store.read_json_mapping(cell_dir / name) is not None for name in outputs)


def _evaluate_enriched_assertions(
    task: Task, task_path: Path, cell_dir: Path
) -> list[AssertionResult]:
    verdict = oracle.evaluate_task(task_path, cell_dir)
    spec_by_id = {
        str(item.get("id")): item for item in task.oracle.assertions if item.get("id") is not None
    }
    results: list[AssertionResult] = []
    for check in verdict.checks:
        spec = spec_by_id.get(check.assertion_id, {})
        predicate = str(spec["predicate"]) if spec.get("predicate") else None
        raw_tier = str(spec["tier"]) if spec.get("tier") else None
        tier = infer_assertion_tier(str(spec.get("type", "")), explicit_tier=raw_tier)
        results.append(
            AssertionResult(
                assertion_id=check.assertion_id,
                predicate=predicate,
                tier=tier,
                passed=check.passed,
                detail=check.message,
            )
        )
    return results


def measure_trial(
    task_path: Path,
    cell_dir: Path,
    *,
    key: TrialKey,
    options: TrialMeasurementOptions | None = None,
) -> TrialMeasurement:
    """Score one agent trial directory and return a validated TrialMeasurement DTO."""
    opts = options or TrialMeasurementOptions()
    task = load_task(task_path)
    assertions = _evaluate_enriched_assertions(task, task_path, cell_dir)
    readable = _deliverable_readable(task, cell_dir)
    transcript_records = _read_transcript_records(cell_dir)
    economics = extract_transcript_metrics(
        transcript_records,
        wall_seconds=opts.wall_seconds,
        tokens=opts.token_usage,
    )
    audit = determinism_report_to_audit(opts.determinism) if opts.determinism is not None else None
    return TrialMeasurement.build(
        key=key,
        assertions=assertions,
        deliverable_readable=readable,
        determinism=audit,
        economics=economics,
    )


def _mapping_field(record: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    raw = record.get(name)
    return raw if isinstance(raw, Mapping) else {}


def _optional_nonneg_int(value: Any) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _optional_minutes_to_seconds(value: Any) -> float | None:
    if type(value) in (int, float) and value >= 0:
        return float(value) * 60.0
    return None


def _human_economics(record: Mapping[str, Any]) -> CostAndProcessMetrics:
    session = _mapping_field(record, "session")
    metrics = _mapping_field(record, "study_metrics")
    return CostAndProcessMetrics(
        wall_seconds=_optional_minutes_to_seconds(session.get("elapsed_minutes")),
        tool_calls=_optional_nonneg_int(metrics.get("processing_step_count")),
        human_steps=_optional_nonneg_int(session.get("steps")),
    )


def _human_assertions(
    record: Mapping[str, Any],
    task_path: Path | None,
    artifacts_dir: Path | None,
) -> tuple[list[AssertionResult], bool | None]:
    if task_path is not None and artifacts_dir is not None:
        task = load_task(task_path)
        return _evaluate_enriched_assertions(task, task_path, artifacts_dir), _deliverable_readable(
            task, artifacts_dir
        )
    recorded_pass = record.get("oracle_passed")
    if isinstance(recorded_pass, bool):
        return [
            AssertionResult(
                assertion_id="recorded-oracle", passed=recorded_pass, detail="from record"
            )
        ], None
    return [], None


def measure_human_reference(
    record: Mapping[str, Any],
    *,
    task_path: Path | None = None,
    artifacts_dir: Path | None = None,
    repetition: int = 1,
    determinism: DeterminismReport | None = None,
) -> TrialMeasurement:
    """Convert an experiment-qgis-plugin v2 human-reference record into a TrialMeasurement DTO."""
    task_id = str(record.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("human reference record is missing a valid task_id")
    key = TrialKey(
        task_id=task_id,
        paradigm="human_gui",
        enforcement_level="none",
        repetition=repetition,
    )
    assertions, readable = _human_assertions(record, task_path, artifacts_dir)
    audit = determinism_report_to_audit(determinism) if determinism is not None else None
    return TrialMeasurement.build(
        key=key,
        assertions=assertions,
        deliverable_readable=readable,
        determinism=audit,
        economics=_human_economics(record),
    )
