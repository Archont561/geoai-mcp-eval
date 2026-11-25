"""Traceable human-reference study metrics separated from raw host observations.

Pure Python with no QGIS, Qt, or qgis-sdk imports. Study metrics follow the
human-reference protocol: steps are counted only from real Processing algorithm
executions and manually reviewed action groups, never from raw host observations
or free-text notes. When evidence is missing or manual review is pending,
top-level study steps and tools stay ``None`` (JSON ``null``) rather than
inventing values or presenting an empty list as a verified result.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MetricsStatus(StrEnum):
    """Review state of derived human-baseline study metrics."""

    NOT_STARTED = "not_started"
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"


class SessionStatus(StrEnum):
    """Lifecycle state of a human-baseline recording session."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    RECORDED = "recorded"
    ABANDONED = "abandoned"


class TrajectoryOrigin(StrEnum):
    """Provenance source of a reconstructed human-baseline trajectory step."""

    HOST_PROCESSING = "host:processing"
    PROCESSING_LOG = "processing_log"
    SESSION_MANUAL = "session_manual"
    POST_SESSION_REVIEW = "post_session_review"


METRICS_STATUS_NOT_STARTED: MetricsStatus = MetricsStatus.NOT_STARTED
METRICS_STATUS_PENDING_REVIEW: MetricsStatus = MetricsStatus.PENDING_REVIEW
METRICS_STATUS_REVIEWED: MetricsStatus = MetricsStatus.REVIEWED


def ordered_unique(items: Iterable[str]) -> list[str]:
    """Return unique non-empty strings preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def normalize_timestamp(raw: Any) -> str | None:
    """Convert a QDateTime, datetime, or string timestamp into an ISO string."""
    if raw is None:
        return None
    if hasattr(raw, "toPyDateTime"):
        raw = raw.toPyDateTime()
    if isinstance(raw, datetime):
        return raw.isoformat()
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    return str(raw)


def sanitize_parameters(raw: Any) -> dict[str, Any] | None:
    """Return a JSON-safe copy of a Processing parameter mapping."""
    if not isinstance(raw, Mapping):
        return None
    return json.loads(json.dumps(dict(raw), sort_keys=True, default=str))


@dataclass(frozen=True)
class ProcessingExecution:
    """One observed QGIS Processing algorithm execution."""

    ts: str
    algorithm_id: str
    parameters: dict[str, Any] | None = None
    history_entry_id: int | None = None
    entry_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ts": self.ts, "algorithm_id": self.algorithm_id}
        if self.parameters is not None:
            payload["parameters"] = self.parameters
        if self.history_entry_id is not None:
            payload["history_entry_id"] = self.history_entry_id
        if self.entry_timestamp is not None:
            payload["entry_timestamp"] = self.entry_timestamp
        return payload


@dataclass(frozen=True)
class ManualActionGroup:
    """One explicitly recorded manual GIS action group."""

    ts: str
    action_group: str
    tool: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "action_group": self.action_group,
            "tool": self.tool,
        }


@dataclass
class SessionMetricsState:
    """Accumulates raw observation metadata separately from study evidence."""

    raw_event_count: int = 0
    observation_sources: list[str] = field(default_factory=list)
    hooks_connected: list[str] = field(default_factory=list)
    hook_failures: list[str] = field(default_factory=list)
    processing_hook_connected: bool = False
    processing_history_incomplete: bool = False
    processing_executions: list[ProcessingExecution] = field(default_factory=list)
    manual_action_groups: list[ManualActionGroup] = field(default_factory=list)

    def note_observation_source(self, source: str | None) -> None:
        if source and source not in self.observation_sources:
            self.observation_sources.append(source)

    def pending_reasons(self, *, manual_review_complete: bool) -> list[str]:
        reasons: list[str] = []
        if not self.processing_hook_connected:
            reasons.append("processing_history_unavailable")
        if self.processing_history_incomplete:
            reasons.append("processing_history_incomplete")
        if not manual_review_complete:
            reasons.append("manual_review_pending")
        return reasons

    def processing_tools(self) -> list[str] | None:
        if not self.processing_hook_connected and not self.processing_executions:
            return None
        return ordered_unique(item.algorithm_id for item in self.processing_executions)

    def processing_step_count(self) -> int | None:
        if not self.processing_hook_connected and not self.processing_executions:
            return None
        return len(self.processing_executions)

    def build_observations(self) -> dict[str, Any]:
        return {
            "raw_event_count": self.raw_event_count,
            "sources": list(self.observation_sources),
            "hooks_connected": list(self.hooks_connected),
            "hook_failures": list(self.hook_failures),
        }

    def build_summary(
        self, *, manual_review_complete: bool = False
    ) -> tuple[int | None, list[str] | None, str, dict[str, Any]]:
        reasons = self.pending_reasons(manual_review_complete=manual_review_complete)
        proc_tools = self.processing_tools()
        proc_count = self.processing_step_count()
        reviewed = not reasons
        if reviewed:
            manual_count: int | None = len(self.manual_action_groups)
            steps: int | None = (proc_count or 0) + manual_count
            manual_tools = [item.tool for item in self.manual_action_groups if item.tool]
            tools: list[str] | None = ordered_unique([*(proc_tools or []), *manual_tools])
            status = METRICS_STATUS_REVIEWED
        else:
            manual_count = None
            steps = None
            tools = None
            status = METRICS_STATUS_PENDING_REVIEW
        detail = {
            "status": status,
            "pending_reasons": reasons,
            "processing_hook_connected": self.processing_hook_connected,
            "processing_step_count": proc_count,
            "processing_tools": proc_tools,
            "processing_executions": [item.to_dict() for item in self.processing_executions],
            "manual_action_groups": [item.to_dict() for item in self.manual_action_groups],
            "manual_step_count": manual_count,
            "manual_review_completed": manual_review_complete,
        }
        return steps, tools, status, detail


def study_metrics_skeleton() -> dict[str, Any]:
    """Blank study_metrics block matching human-reference-record.template.json."""
    return {
        "status": METRICS_STATUS_NOT_STARTED,
        "pending_reasons": [],
        "processing_hook_connected": None,
        "processing_step_count": None,
        "processing_tools": None,
        "processing_executions": [],
        "manual_action_groups": [],
        "manual_step_count": None,
        "manual_review_completed": False,
    }
