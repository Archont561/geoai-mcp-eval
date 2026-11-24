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

import hashlib
import json
import os
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from experiment_plugin import __version__

# Single source of truth is experiment_plugin.__version__. pyproject.toml carries the
# same literal because qgis-sdk build reads [project] version statically (it rejects
# PEP 621 dynamic with META002); test_version_is_single_sourced pins the two equal.
RECORDER_VERSION = __version__
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
    "outputs",
    "oracle_report_path",
    "oracle_passed",
    "evidence_storage_reference",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_task_dir(base_dir: str | Path) -> Path:
    path = Path(base_dir).expanduser()
    return path.resolve()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    import yaml  # local import: pyyaml ships with the pixi env

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def find_task_yaml(base_dir: Path, task_id: str) -> Path:
    parse_errors: list[str] = []
    for candidate in sorted(base_dir.glob("*.yaml")):
        try:
            data = _load_yaml_mapping(candidate)
        except Exception as exc:  # unreadable YAML: report, don't hide it
            parse_errors.append(f"{candidate.name}: {exc}")
            continue
        if data.get("id") == task_id:
            return candidate
    detail = f" (parse errors: {'; '.join(parse_errors)})" if parse_errors else ""
    raise FileNotFoundError(f"no task YAML with id={task_id!r} under {base_dir}{detail}")


def task_fixture(task_yaml: Path) -> Path:
    import yaml

    data = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
    return (task_yaml.parent / data["fixtures"]["input"]).resolve()


def baseline_dir_for(task_yaml: Path, task_id: str) -> Path:
    # experiment/tasks/baselines/<id> — matches .gitignore and HUMAN-REFERENCE.md
    return (task_yaml.parent / "baselines" / task_id).resolve()


def template_skeleton() -> dict[str, Any]:
    return {
        "record_version": 1,
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
            "tools": [],
            "software_versions": {"qgis": None, "gdal": None, "geos": None, "proj": None},
            "network_disabled": None,
            "deviations_or_interruptions": [],
        },
        "outputs": [],
        "oracle_report_path": None,
        "oracle_passed": None,
        "evidence_storage_reference": None,
    }


def host_software_versions() -> dict[str, str | None]:
    """Best-effort versions; each is None when the host did not say."""
    versions: dict[str, str | None] = {
        "qgis": os.environ.get("QGIS_VERSION"),
        "gdal": os.environ.get("GDAL_VERSION"),
        "geos": os.environ.get("GEOS_VERSION"),
        "proj": os.environ.get("PROJ_VERSION"),
    }
    try:  # PyQGIS hosts usually can answer properly
        import qgis.core  # type: ignore[import-not-found]

        versions["qgis"] = versions["qgis"] or getattr(qgis.core, "QGIS_VERSION", None)
        for key, attr in (
            ("gdal", "GDAL_VERSION"),
            ("geos", "GEOS_VERSION"),
            ("proj", "PROJ_VERSION"),
        ):
            versions[key] = versions[key] or getattr(qgis.core, attr, None)
    except ImportError:
        pass
    return versions


def host_identity() -> dict[str, str]:
    """Non-identifying environment facts (no hostname, no user name)."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


@dataclass
class BehaviorTracker:
    """Append-only behavior event log written as JSONL."""

    events_path: Path
    started_at: datetime = field(default_factory=utc_now)
    event_count: int = 0

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": utc_now().isoformat(),
            "event": event,
            **{k: v for k, v in fields.items() if v is not None},
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self.event_count += 1
        return record


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
    tools_used: list[str] = field(default_factory=list)
    status: str = "in_progress"

    # -- events -----------------------------------------------------------

    def log(self, event: str, tool: str | None = None, **fields: Any) -> None:
        if tool and tool not in self.tools_used:
            self.tools_used.append(tool)
        self.tracker.record(event, tool=tool, **fields)

    # -- finish -----------------------------------------------------------

    def _collect_outputs(self) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        excluded = {"events.jsonl", "human-reference-record.json"}
        for path in sorted(self.output_dir.glob("*")):
            if path.is_file() and path.name not in excluded:
                outputs.append(
                    {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
                )
        return outputs

    def _build_record(self, ended: datetime, outputs: list[dict[str, Any]]) -> dict[str, Any]:
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
        elapsed = round((ended - self.started_at).total_seconds() / 60, 2)
        record["session"].update(
            {
                "started_at_utc": self.started_at.isoformat(),
                "ended_at_utc": ended.isoformat(),
                "elapsed_minutes": elapsed,
                "steps": max(0, self.tracker.event_count - 1),  # exclude session_start marker
                "tools": list(self.tools_used),
                "software_versions": host_software_versions(),
                "network_disabled": self.network_disabled,
                "deviations_or_interruptions": [],
            }
        )
        record["outputs"] = outputs
        record["recorder"] = f"experiment-plugin session recorder v{RECORDER_VERSION}"
        record["environment"] = host_identity()
        record["events_path"] = "events.jsonl"
        return record

    def finish(self) -> Path:
        ended = utc_now()
        outputs = self._collect_outputs()
        record = self._build_record(ended, outputs)
        record_path = self.output_dir / "human-reference-record.json"
        # Publish beside the event log only after its terminal event is written.
        pending: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.output_dir,
                prefix=".human-reference-record-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                pending = Path(handle.name)
                handle.write(json.dumps(record, indent=2, sort_keys=True))
            self.tracker.record("session_end", outputs=len(outputs))
            pending.replace(record_path)
        except BaseException as error:
            if pending is not None:
                try:
                    pending.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    raise BaseExceptionGroup(
                        "record writing and cleanup failed", [error, cleanup_error]
                    ) from None
            raise
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
    try:
        raw_lines = session.tracker.events_path.read_text(encoding="utf-8").splitlines()
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


def abandon_session(session: HumanBaselineSession, reason: str = "user requested") -> Path:
    """Abandon a session without writing human-reference-record.json.

    The event log stays on disk and gains a ``session_abandoned`` marker; a
    small ``session-abandoned.json`` is written next to it so the directory is
    recognisably an abandoned take, not an unfinished recording. The record is
    NOT written — whatever was measured is not promoted to reference evidence.
    Returns the marker path.
    """
    session.tracker.record("session_abandoned", reason=reason)
    abandoned_at = utc_now()
    marker = session.output_dir / "session-abandoned.json"
    marker.write_text(
        json.dumps(
            {
                "task_id": session.task_id,
                "abandoned_at_utc": abandoned_at.isoformat(),
                "reason": reason,
                "started_at_utc": session.started_at.isoformat(),
                "event_count": session.tracker.event_count,
                "tools_used": list(session.tools_used),
                "record_written": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
