"""Merge recorded executions, manual actions, and trajectories for post-session review."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiment_plugin import metrics
from experiment_plugin._processing_log import clean_text as _clean_text


@dataclass(frozen=True)
class ReviewActionInput:
    """One audited manual GIS action group supplied during post-session review."""

    action_group: str
    tool: str | None = None
    ts: str | None = None


@dataclass(frozen=True)
class LogMergeSummary:
    """Provenance summary of an optional QGIS ``processing.log`` merge."""

    log_path: Path | None
    log_sha256: str | None
    log_errors: list[str]


def normalize_manual_inputs(
    entries: Sequence[ReviewActionInput | Mapping[str, Any]], default_ts: str
) -> list[metrics.ManualActionGroup]:
    """Validate and normalize user-supplied manual action groups."""
    normalized: list[metrics.ManualActionGroup] = []
    for entry in entries:
        if isinstance(entry, ReviewActionInput):
            raw_group, raw_tool, raw_ts = entry.action_group, entry.tool, entry.ts
        elif isinstance(entry, Mapping):
            raw_group, raw_tool, raw_ts = (
                entry.get("action_group", ""),
                entry.get("tool"),
                entry.get("ts"),
            )
        else:
            raise ValueError("manual_actions entries must be ReviewActionInput or mapping")
        clean_group = _clean_text(raw_group)
        if not clean_group:
            raise ValueError("action_group must be non-empty")
        normalized.append(
            metrics.ManualActionGroup(
                ts=_clean_text(raw_ts) or default_ts,
                action_group=clean_group,
                tool=_clean_text(raw_tool),
            )
        )
    return normalized


def execution_dedup_key(item: metrics.ProcessingExecution) -> tuple[str, str, str]:
    """Deduplication fingerprint for a Processing execution across history and log sources."""
    params_key = json.dumps(item.parameters, sort_keys=True) if item.parameters is not None else ""
    raw_ts = item.entry_timestamp or item.ts or ""
    ts_prefix = raw_ts.replace(" ", "T", 1)[:19]
    return (item.algorithm_id, params_key, ts_prefix)


def _to_recorded_execution(raw: Any) -> metrics.ProcessingExecution | None:
    if not isinstance(raw, Mapping):
        return None
    alg_id = raw.get("algorithm_id")
    if not alg_id:
        return None
    params = metrics.sanitize_parameters(raw.get("parameters"))
    entry_ts = _clean_text(raw.get("entry_timestamp"))
    return metrics.ProcessingExecution(
        ts=str(raw.get("ts") or ""),
        algorithm_id=str(alg_id),
        parameters=params,
        history_entry_id=raw.get("history_entry_id"),
        entry_timestamp=entry_ts,
    )


def load_recorded_executions(
    raw_study: Mapping[str, Any],
) -> list[tuple[metrics.ProcessingExecution, str]]:
    """Extract previously recorded Processing executions from ``study_metrics``."""
    recorded: list[tuple[metrics.ProcessingExecution, str]] = []
    for raw in raw_study.get("processing_executions") or []:
        execution = _to_recorded_execution(raw)
        if execution is not None:
            recorded.append((execution, "host:processing"))
    return recorded


def _to_recorded_manual_group(raw: Any) -> metrics.ManualActionGroup | None:
    if not isinstance(raw, Mapping):
        return None
    group_name = _clean_text(raw.get("action_group"))
    if not group_name:
        return None
    return metrics.ManualActionGroup(
        ts=str(raw.get("ts") or ""),
        action_group=group_name,
        tool=_clean_text(raw.get("tool")),
    )


def load_recorded_manual_groups(
    raw_study: Mapping[str, Any],
) -> list[tuple[metrics.ManualActionGroup, str]]:
    """Extract previously recorded manual action groups from ``study_metrics``."""
    recorded: list[tuple[metrics.ManualActionGroup, str]] = []
    for raw in raw_study.get("manual_action_groups") or []:
        group = _to_recorded_manual_group(raw)
        if group is not None:
            recorded.append((group, "session_manual"))
    return recorded


def _trajectory_rows(
    executions: Sequence[tuple[metrics.ProcessingExecution, str]],
    manual_groups: Sequence[tuple[metrics.ManualActionGroup, str]],
) -> list[tuple[str, int, dict[str, Any]]]:
    rows: list[tuple[str, int, dict[str, Any]]] = []
    for item, origin in executions:
        entry = {**item.to_dict(), "kind": "processing_execution", "origin": origin}
        rows.append((item.entry_timestamp or item.ts or "", len(rows), entry))
    for group, origin in manual_groups:
        entry = {**group.to_dict(), "kind": "manual_action_group", "origin": origin}
        rows.append((group.ts or "", len(rows), entry))
    return rows


def build_trajectory(
    executions: Sequence[tuple[metrics.ProcessingExecution, str]],
    manual_groups: Sequence[tuple[metrics.ManualActionGroup, str]],
) -> list[dict[str, Any]]:
    """Merge executions and manual action groups into a time-ordered sequence."""
    raw_entries = _trajectory_rows(executions, manual_groups)
    raw_entries.sort(key=lambda row: (row[0], row[1]))
    return [{"seq": seq, **entry} for seq, (_, _, entry) in enumerate(raw_entries, start=1)]


def compute_reviewed_metrics(
    raw_study: Mapping[str, Any],
    executions: Sequence[tuple[metrics.ProcessingExecution, str]],
    manual_groups: Sequence[tuple[metrics.ManualActionGroup, str]],
    log_summary: LogMergeSummary,
    *,
    mark_reviewed: bool,
) -> tuple[int | None, list[str] | None, str, dict[str, Any]]:
    """Recompute session step/tool summary and study metrics after merging review inputs."""
    raw_pending = list(raw_study.get("pending_reasons") or [])
    connected = bool(raw_study.get("processing_hook_connected")) or (
        log_summary.log_path is not None
    )
    incomplete = (
        bool(log_summary.log_errors)
        if log_summary.log_path is not None
        else ("processing_history_incomplete" in raw_pending)
    )
    state = metrics.SessionMetricsState(
        processing_hook_connected=connected,
        processing_history_incomplete=incomplete,
        processing_executions=[item for item, _ in executions],
        manual_action_groups=[group for group, _ in manual_groups],
    )
    return state.build_summary(manual_review_complete=mark_reviewed)
