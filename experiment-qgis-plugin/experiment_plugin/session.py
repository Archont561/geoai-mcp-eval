"""Human-baseline session recorder for the experiment plugin.

No top-level QGIS, Qt, or qgis-sdk imports — the recorder is testable outside
QGIS. Plugin actions and host-observation hooks supply session events; the
record it produces mirrors
`experiment/tasks/human-reference-record.template.json` as closely as the host
can truthfully provide. Fields the host cannot know (consent, oracle gate
results, evidence storage reference) stay null — never invented.

Outputs (in the task's gitignored baseline dir; one subdirectory per session):
  <task YAML dir>/baselines/<task_id>/session-<started_at_utc>/events.jsonl
  <task YAML dir>/baselines/<task_id>/session-<started_at_utc>/human-reference-record.json
Both files live in the session's own directory; the record is written at end_session.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from experiment_plugin import __version__, _io, _tasks, _versions
from experiment_plugin._tasks import (
    BehaviorTracker,
    baseline_dir_for,
    find_task_yaml,
    resolve_task_dir,
    sha256_file,
    task_fixture,
    utc_now,
)
from experiment_plugin.metrics import (
    METRICS_STATUS_NOT_STARTED,
    ManualActionGroup,
    ProcessingExecution,
    SessionMetricsState,
    normalize_timestamp,
    sanitize_parameters,
    study_metrics_skeleton,
)

# Single source of truth is experiment_plugin.__version__. pyproject.toml carries the
# same literal because qgis-sdk build reads [project] version statically (it rejects
# PEP 621 dynamic with META002); test_version_is_single_sourced pins the two equal.
RECORDER_VERSION = __version__
RECORD_VERSION = 2
TEMPLATE_KEYS = (
    "record_version",
    "status",
    "task_id",
    "task_file_sha256",
    "fixture_path",
    "fixture_sha256",
    "participant_code",
    "consent",
    "session",
    "study_metrics",
    "outputs",
    "oracle_report_path",
    "oracle_passed",
    "evidence_storage_reference",
)


def discover_task_dir(*, cwd: Path | None = None, anchor: Path | None = None) -> Path:
    """Locate experiment/tasks from cwd ancestors, then package ancestors."""
    return _tasks.discover_task_dir(cwd=cwd, anchor=anchor or Path(__file__))


def template_skeleton() -> dict[str, Any]:
    return {
        "record_version": RECORD_VERSION,
        "status": "not_started",
        "task_id": None,
        "task_file_sha256": None,
        "fixture_path": None,
        "fixture_sha256": None,
        "participant_code": None,
        "consent": {"obtained": None, "screen_recording": False},
        "session": {
            "started_at_utc": None,
            "ended_at_utc": None,
            "elapsed_minutes": None,
            "steps": None,
            "tools": None,
            "metrics_status": METRICS_STATUS_NOT_STARTED,
            "software_versions": {"qgis": None, "gdal": None, "geos": None, "proj": None},
            "network_disabled": None,
            "deviations_or_interruptions": [],
        },
        "study_metrics": study_metrics_skeleton(),
        "outputs": [],
        "oracle_report_path": None,
        "oracle_passed": None,
        "evidence_storage_reference": None,
    }


def host_software_versions() -> dict[str, str | None]:
    """Best-effort versions; each is None when the host did not say."""
    return _versions.host_software_versions()


def host_identity() -> dict[str, str]:
    """Non-identifying environment facts (no hostname, no user name)."""
    return _versions.host_identity()


@dataclass
class HumanBaselineSession:
    """One start→end human-baseline session for one task."""

    task_id: str
    task_yaml: Path
    fixture: Path
    output_dir: Path
    tracker: BehaviorTracker
    started_at: datetime
    participant_code: str | None = None
    # None = the host did not verify network isolation (every host today); never
    # default to True, which would fabricate an offline session the host never enforced.
    network_disabled: bool | None = None
    metrics: SessionMetricsState = field(default_factory=SessionMetricsState)
    status: str = "in_progress"

    # -- events -----------------------------------------------------------

    def log(self, event: str, source: str | None = None, **fields: Any) -> None:
        self.metrics.note_observation_source(source)
        self.metrics.raw_event_count += 1
        self.tracker.record(event, source=source, **fields)

    def record_processing_execution(
        self,
        algorithm_id: str,
        *,
        parameters: Any = None,
        history_entry_id: int | None = None,
        entry_timestamp: Any = None,
    ) -> dict[str, Any]:
        clean_params = sanitize_parameters(parameters)
        clean_ts = normalize_timestamp(entry_timestamp)
        entry = self.tracker.record(
            "processing_algorithm",
            source="host:processing",
            algorithm_id=algorithm_id,
            parameters=clean_params,
            history_entry_id=history_entry_id,
            entry_timestamp=clean_ts,
        )
        self.metrics.processing_executions.append(
            ProcessingExecution(
                ts=entry["ts"],
                algorithm_id=algorithm_id,
                parameters=clean_params,
                history_entry_id=history_entry_id,
                entry_timestamp=clean_ts,
            )
        )
        return entry

    def record_unparsed_processing_entry(
        self, *, history_entry_id: int | None = None, detail: str = "missing algorithm_id"
    ) -> dict[str, Any]:
        self.metrics.processing_history_incomplete = True
        self.metrics.note_observation_source("host:processing")
        self.metrics.raw_event_count += 1
        return self.tracker.record(
            "processing_history_unparsed",
            source="host:processing",
            history_entry_id=history_entry_id,
            detail=detail,
        )

    def record_manual_action_group(
        self, action_group: str, *, tool: str | None = None
    ) -> dict[str, Any]:
        clean_group = action_group.strip()
        if not clean_group:
            raise ValueError("action_group must be non-empty")
        clean_tool = tool.strip() if isinstance(tool, str) and tool.strip() else None
        entry = self.tracker.record(
            "manual_action_group",
            source="manual",
            action_group=clean_group,
            tool=clean_tool,
        )
        self.metrics.manual_action_groups.append(
            ManualActionGroup(ts=entry["ts"], action_group=clean_group, tool=clean_tool)
        )
        return entry

    def set_hook_status(
        self, connected: list[str], failures: list[str], *, processing_connected: bool
    ) -> None:
        self.metrics.hooks_connected = list(connected)
        self.metrics.hook_failures = list(failures)
        self.metrics.processing_hook_connected = processing_connected

    # -- finish -----------------------------------------------------------

    def _collect_outputs(self) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        root_excluded = {
            "events.jsonl",
            "human-reference-record.json",
            "session-abandoned.json",
        }
        candidates: list[tuple[str, Path]] = []
        for dirpath, _dirnames, filenames in os.walk(self.output_dir, followlinks=False):
            current_dir = Path(dirpath)
            for name in filenames:
                path = current_dir / name
                if path.is_symlink() or not path.is_file():
                    continue
                rel = path.relative_to(self.output_dir).as_posix()
                if rel in root_excluded:
                    continue
                if "/" not in rel and name.startswith(".human-reference-record-"):
                    continue
                candidates.append((rel, path))
        for rel, path in sorted(candidates, key=lambda item: item[0]):
            outputs.append({"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size})
        return outputs

    def _session_section(
        self,
        ended: datetime,
        steps: int | None,
        tools: list[str] | None,
        metrics_status: str,
    ) -> dict[str, Any]:
        return {
            "started_at_utc": self.started_at.isoformat(),
            "ended_at_utc": ended.isoformat(),
            "elapsed_minutes": round((ended - self.started_at).total_seconds() / 60, 2),
            "steps": steps,
            "tools": tools,
            "metrics_status": metrics_status,
            "software_versions": host_software_versions(),
            "network_disabled": self.network_disabled,
            "deviations_or_interruptions": [],
        }

    def _build_record(
        self,
        ended: datetime,
        outputs: list[dict[str, Any]],
        *,
        manual_review_complete: bool = False,
    ) -> dict[str, Any]:
        record = template_skeleton()
        record.update(
            {
                "status": "recorded",
                "task_id": self.task_id,
                "task_file_sha256": sha256_file(self.task_yaml),
                "fixture_path": str(self.fixture),
                "fixture_sha256": sha256_file(self.fixture),
                "participant_code": self.participant_code,
            }
        )
        steps, tools, metrics_status, study_metrics = self.metrics.build_summary(
            manual_review_complete=manual_review_complete
        )
        record["session"].update(self._session_section(ended, steps, tools, metrics_status))
        record["study_metrics"] = study_metrics
        record["observations"] = self.metrics.build_observations()
        record["outputs"] = outputs
        record["recorder"] = f"experiment-plugin session recorder v{RECORDER_VERSION}"
        record["environment"] = host_identity()
        record["events_path"] = "events.jsonl"
        return record

    def finish(self, *, manual_review_complete: bool = False) -> Path:
        ended = utc_now()
        outputs = self._collect_outputs()
        record = self._build_record(ended, outputs, manual_review_complete=manual_review_complete)
        record_path = self.output_dir / "human-reference-record.json"
        # Publish beside the event log only after its terminal event is written.
        _io.write_atomic_text(
            record_path,
            _io.format_json(record),
            prefix=".human-reference-record-",
            before_replace=lambda: self.tracker.record("session_end", outputs=len(outputs)),
        )
        self.status = "recorded"
        return record_path


def render_log(session: HumanBaselineSession) -> str:
    """Human-readable rendering of a session's event log, for display and export.

    Rendered line: ``<ts>  <event>  key=value key=value`` with keys sorted; no
    values invented. A missing or unreadable events file yields a header that
    says so instead of an exception.
    """
    lines = [
        f"human-baseline session log — task {session.task_id}",
        f"session dir: {session.output_dir}",
        f"started: {session.started_at.isoformat()}   status: {session.status}",
        "",
    ]
    events_path = session.tracker.events_path
    try:
        raw_lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        lines.append(f"(event log unavailable: {exc})")
        return "\n".join(lines) + "\n"
    for raw in raw_lines:
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            lines.append(raw)
            continue
        ts = record.pop("ts", "?")
        event = record.pop("event", "?")
        fields = "  ".join(f"{k}={v}" for k, v in sorted(record.items()) if v is not None)
        lines.append(f"{ts}  {event}  {fields}".rstrip())
    return "\n".join(lines) + "\n"


def _abandoned_payload(
    session: HumanBaselineSession, abandoned_at: datetime, reason: str
) -> dict[str, Any]:
    return {
        "task_id": session.task_id,
        "abandoned_at_utc": abandoned_at.isoformat(),
        "reason": reason,
        "started_at_utc": session.started_at.isoformat(),
        "event_count": session.tracker.event_count,
        "observation_sources": list(session.metrics.observation_sources),
        "processing_executions": len(session.metrics.processing_executions),
        "manual_action_groups": len(session.metrics.manual_action_groups),
        "record_written": False,
    }


def abandon_session(session: HumanBaselineSession, reason: str = "user requested") -> Path:
    """Abandon a session without writing human-reference-record.json."""
    session.tracker.record("session_abandoned", reason=reason)
    marker = session.output_dir / "session-abandoned.json"
    payload = _abandoned_payload(session, utc_now(), reason)
    marker.write_text(_io.format_json(payload, trailing_newline=True), encoding="utf-8")
    session.status = "abandoned"
    return marker


def start_session(
    task_id: str,
    base_dir: str | Path,
    *,
    participant_code: str | None = None,
    network_disabled: bool | None = None,
) -> HumanBaselineSession:
    base = resolve_task_dir(base_dir)
    task_yaml = find_task_yaml(base, task_id)
    fixture = task_fixture(task_yaml)
    session = _new_session(task_id, task_yaml, fixture, participant_code, network_disabled)
    session.tracker.record(
        "session_start",
        task_id=task_id,
        task_file_sha256=sha256_file(task_yaml),
        fixture_sha256=sha256_file(fixture),
    )
    return session


def _new_session(
    task_id: str,
    task_yaml: Path,
    fixture: Path,
    participant_code: str | None,
    network_disabled: bool | None,
) -> HumanBaselineSession:
    root = baseline_dir_for(task_yaml, task_id)
    started = utc_now()
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    output_dir = root / f"session-{stamp}"
    attempt = 1
    while output_dir.exists():  # same-second restarts: never clobber a sibling session
        attempt += 1
        output_dir = root / f"session-{stamp}-{attempt}"
    output_dir.mkdir(parents=True)
    tracker = BehaviorTracker(events_path=output_dir / "events.jsonl", started_at=started)
    return HumanBaselineSession(
        task_id=task_id,
        task_yaml=task_yaml,
        fixture=fixture,
        output_dir=output_dir,
        tracker=tracker,
        started_at=started,
        participant_code=participant_code or None,
        network_disabled=network_disabled,
    )
