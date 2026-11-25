"""Non-destructive post-session review for human-baseline takes.

Pure Python with no QGIS, Qt, or qgis-sdk imports. Reads an immutable completed
``session-<ts>/`` directory (``human-reference-record.json`` + ``events.jsonl``),
merges any audited manual action groups and optional QGIS ``processing.log``
executions, and atomically writes separate derived artifacts:

- ``human-reference-record.reviewed.json``
- ``human_trajectory.jsonl``

Raw evidence files (``events.jsonl``, ``human-reference-record.json``, outputs,
and task YAMLs) are never modified.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment_plugin import _io, _processing_log, _review_cli, _review_merge, metrics, session
from experiment_plugin._processing_log import clean_text as _clean_text
from experiment_plugin._review_merge import LogMergeSummary, ReviewActionInput

REVIEWED_RECORD_FILENAME = "human-reference-record.reviewed.json"
TRAJECTORY_FILENAME = "human_trajectory.jsonl"

__all__ = [
    "REVIEWED_RECORD_FILENAME",
    "TRAJECTORY_FILENAME",
    "ReviewActionInput",
    "ReviewError",
    "ReviewResult",
    "format_review_summary",
    "main",
    "parse_processing_log",
    "review_session",
]


class ReviewError(ValueError):
    """Raised when a session directory or review input is invalid."""


@dataclass(frozen=True)
class ReviewResult:
    """Derived review artifacts written alongside (or outside) the raw session take."""

    reviewed_record_path: Path
    trajectory_path: Path
    record: dict[str, Any]
    trajectory_entries: list[dict[str, Any]]


@dataclass(frozen=True)
class _ReviewMetadata:
    reviewed_ts: str
    reviewer: str | None
    notes: str | None
    mark_reviewed: bool
    added_manual_count: int


@dataclass(frozen=True)
class _ReviewRequest:
    manual_actions: Sequence[ReviewActionInput | Mapping[str, Any]]
    mark_reviewed: bool
    reviewer: str | None
    notes: str | None
    processing_log: str | Path | None
    reviewed_ts: str


def parse_processing_log(
    log_path: str | Path,
) -> tuple[list[metrics.ProcessingExecution], list[str]]:
    """Parse QGIS ``processing.log`` ``ALGORITHM|...`` lines without executing code."""
    path = Path(log_path).expanduser().resolve()
    if not path.is_file():
        raise ReviewError(f"processing log does not exist: {path}")
    return _processing_log.parse_processing_log_file(path)


def _validate_session_dir(session_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    if not session_dir.is_dir():
        raise ReviewError(f"session directory does not exist: {session_dir}")
    if (session_dir / "session-abandoned.json").exists():
        raise ReviewError(f"cannot review abandoned session: {session_dir}")
    record_path = session_dir / "human-reference-record.json"
    if not record_path.is_file():
        raise ReviewError(f"missing human-reference-record.json in {session_dir}")
    events_path = session_dir / "events.jsonl"
    if not events_path.is_file():
        raise ReviewError(f"missing events.jsonl in {session_dir}")
    try:
        raw_record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReviewError(f"unreadable human-reference-record.json: {exc}") from exc
    if not isinstance(raw_record, dict):
        raise ReviewError("human-reference-record.json must contain a JSON object")
    if raw_record.get("record_version") != session.RECORD_VERSION:
        raise ReviewError(
            f"unsupported record_version={raw_record.get('record_version')!r} "
            f"(expected {session.RECORD_VERSION})"
        )
    if raw_record.get("status") != metrics.SessionStatus.RECORDED:
        raise ReviewError(f"session status is {raw_record.get('status')!r}, expected 'recorded'")
    return record_path, events_path, raw_record


def _merge_processing_log(
    executions: list[tuple[metrics.ProcessingExecution, str]],
    processing_log: str | Path | None,
) -> LogMergeSummary:
    if processing_log is None or not _clean_text(processing_log):
        return LogMergeSummary(None, None, [])
    log_path = Path(processing_log).expanduser().resolve()
    parsed_log, log_errors = parse_processing_log(log_path)
    seen_keys = {_review_merge.execution_dedup_key(item) for item, _ in executions}
    for item in parsed_log:
        key = _review_merge.execution_dedup_key(item)
        if key not in seen_keys:
            seen_keys.add(key)
            executions.append((item, metrics.TrajectoryOrigin.PROCESSING_LOG))
    return LogMergeSummary(log_path, session.sha256_file(log_path), log_errors)


def _assemble_reviewed_record(
    raw_record: dict[str, Any],
    sources: tuple[Path, Path],
    summary_tuple: tuple[int | None, list[str] | None, str, dict[str, Any]],
    log_summary: LogMergeSummary,
    meta: _ReviewMetadata,
) -> dict[str, Any]:
    record_path, events_path = sources
    steps, tools, metrics_status, study_metrics = summary_tuple
    reviewed_record = copy.deepcopy(raw_record)
    reviewed_record["session"]["steps"] = steps
    reviewed_record["session"]["tools"] = tools
    reviewed_record["session"]["metrics_status"] = metrics_status
    reviewed_record["study_metrics"] = study_metrics
    reviewed_record["review"] = {
        "reviewed_at_utc": meta.reviewed_ts,
        "reviewer": _clean_text(meta.reviewer),
        "notes": _clean_text(meta.notes),
        "manual_review_completed": meta.mark_reviewed,
        "source_record": record_path.name,
        "source_record_sha256": session.sha256_file(record_path),
        "source_events": events_path.name,
        "source_events_sha256": session.sha256_file(events_path),
        "processing_log_path": str(log_summary.log_path) if log_summary.log_path else None,
        "processing_log_sha256": log_summary.log_sha256,
        "processing_log_parse_errors": log_summary.log_errors,
        "added_manual_action_count": meta.added_manual_count,
    }
    return reviewed_record


def _write_review_artifacts(
    target_dir: Path,
    reviewed_record: dict[str, Any],
    trajectory: list[dict[str, Any]],
) -> ReviewResult:
    reviewed_path = _io.write_atomic_text(
        target_dir / REVIEWED_RECORD_FILENAME,
        _io.format_json(reviewed_record, trailing_newline=True),
        prefix=".human-reference-record-reviewed-",
    )
    trajectory_path = _io.write_atomic_text(
        target_dir / TRAJECTORY_FILENAME,
        _io.format_jsonl(trajectory),
        prefix=".human-trajectory-",
    )
    return ReviewResult(
        reviewed_record_path=reviewed_path,
        trajectory_path=trajectory_path,
        record=reviewed_record,
        trajectory_entries=trajectory,
    )


def _build_reviewed_outputs(
    sources: tuple[Path, Path],
    raw_record: dict[str, Any],
    req: _ReviewRequest,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_study = raw_record.get("study_metrics")
    if not isinstance(raw_study, Mapping):
        raise ReviewError("human-reference-record.json is missing study_metrics")
    added_manual = _review_merge.normalize_manual_inputs(
        req.manual_actions, default_ts=req.reviewed_ts
    )
    executions = _review_merge.load_recorded_executions(raw_study)
    log_summary = _merge_processing_log(executions, req.processing_log)
    manual_groups = _review_merge.load_recorded_manual_groups(raw_study)
    manual_groups.extend(
        (group, metrics.TrajectoryOrigin.POST_SESSION_REVIEW) for group in added_manual
    )
    summary = _review_merge.compute_reviewed_metrics(
        raw_study, executions, manual_groups, log_summary, mark_reviewed=req.mark_reviewed
    )
    meta = _ReviewMetadata(
        req.reviewed_ts, req.reviewer, req.notes, req.mark_reviewed, len(added_manual)
    )
    record = _assemble_reviewed_record(raw_record, sources, summary, log_summary, meta)
    return record, _review_merge.build_trajectory(executions, manual_groups)


def review_session(  # noqa: CC102
    session_dir: str | Path,
    *,
    manual_actions: Sequence[ReviewActionInput | Mapping[str, Any]] = (),
    mark_reviewed: bool = False,
    reviewer: str | None = None,
    notes: str | None = None,
    processing_log: str | Path | None = None,
    output_dir: str | Path | None = None,
    reviewed_at: datetime | None = None,
) -> ReviewResult:
    """Audit a completed session take and emit separate reviewed artifacts."""
    source_dir = Path(session_dir).expanduser().resolve()
    record_path, events_path, raw_record = _validate_session_dir(source_dir)
    req = _ReviewRequest(
        manual_actions=manual_actions,
        mark_reviewed=mark_reviewed,
        reviewer=reviewer,
        notes=notes,
        processing_log=processing_log,
        reviewed_ts=(reviewed_at or datetime.now(UTC)).isoformat(),
    )
    reviewed_record, trajectory = _build_reviewed_outputs(
        (record_path, events_path), raw_record, req
    )
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else source_dir
    return _write_review_artifacts(target_dir, reviewed_record, trajectory)


def format_review_summary(result: ReviewResult) -> str:
    """Format a concise human-readable summary of a completed review."""
    return _review_cli.format_review_summary(result)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for non-destructive post-session review."""
    return _review_cli.run_cli(
        argv,
        review_fn=review_session,
        action_cls=ReviewActionInput,
        error_cls=ReviewError,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
