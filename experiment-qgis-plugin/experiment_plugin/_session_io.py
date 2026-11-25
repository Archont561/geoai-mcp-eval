"""Session directory allocation, template skeleton, output scanning, and log rendering."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from experiment_plugin import _io
from experiment_plugin._tasks import sha256_file
from experiment_plugin.metrics import (
    METRICS_STATUS_NOT_STARTED,
    SessionStatus,
    study_metrics_skeleton,
)

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
_ROOT_EXCLUDED = frozenset(
    {
        "events.jsonl",
        "human-reference-record.json",
        "session-abandoned.json",
    }
)


def template_skeleton() -> dict[str, Any]:
    """Return a blank v2 human-reference-record payload with null defaults."""
    return {
        "record_version": RECORD_VERSION,
        "status": SessionStatus.NOT_STARTED,
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


def collect_session_outputs(output_dir: Path) -> list[dict[str, Any]]:
    """Hash all regular non-control deliverable files written under ``output_dir``."""
    candidates: list[tuple[str, Path]] = []
    for dirpath, _dirnames, filenames in os.walk(output_dir, followlinks=False):
        current_dir = Path(dirpath)
        for name in filenames:
            path = current_dir / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(output_dir).as_posix()
            if rel in _ROOT_EXCLUDED:
                continue
            if "/" not in rel and name.startswith(".human-reference-record-"):
                continue
            candidates.append((rel, path))
    return [
        {"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for rel, path in sorted(candidates, key=lambda item: item[0])
    ]


def _format_event_line(raw: str) -> str:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    ts = record.pop("ts", "?")
    event = record.pop("event", "?")
    fields = "  ".join(f"{k}={v}" for k, v in sorted(record.items()) if v is not None)
    return f"{ts}  {event}  {fields}".rstrip()


def render_session_log(
    *,
    task_id: str,
    output_dir: Path,
    started_at: datetime,
    status: str,
    events_path: Path,
) -> str:
    """Render a session's ``events.jsonl`` into human-readable lines."""
    lines = [
        f"human-baseline session log — task {task_id}",
        f"session dir: {output_dir}",
        f"started: {started_at.isoformat()}   status: {status}",
        "",
    ]
    try:
        raw_lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        lines.append(f"(event log unavailable: {exc})")
        return "\n".join(lines) + "\n"
    lines.extend(_format_event_line(raw) for raw in raw_lines)
    return "\n".join(lines) + "\n"


def write_abandoned_marker(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Write ``session-abandoned.json`` inside ``output_dir``."""
    marker = output_dir / "session-abandoned.json"
    marker.write_text(_io.format_json(payload, trailing_newline=True), encoding="utf-8")
    return marker


def allocate_session_dir(root: Path, started: datetime) -> Path:
    """Create and return a unique ``session-<stamp>`` directory under ``root``."""
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    output_dir = root / f"session-{stamp}"
    attempt = 1
    while output_dir.exists():  # same-second restarts: never clobber a sibling session
        attempt += 1
        output_dir = root / f"session-{stamp}-{attempt}"
    output_dir.mkdir(parents=True)
    return output_dir
