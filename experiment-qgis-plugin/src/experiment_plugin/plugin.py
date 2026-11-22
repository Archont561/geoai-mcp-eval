"""Experiment Plugin: human-baseline session recorder (plus hello demo)."""

from __future__ import annotations

import os

from qgis_sdk import QgisSdkPlugin
from qgis_sdk.core import PluginContext

from experiment_plugin import session as baseline

MAX_EVENTS = 2000
DEFAULT_TASK_ID = "prep-axis-order-001"

app = QgisSdkPlugin(id="experiment_plugin", title="Experiment Plugin")

# Single active session: the right shape for a single-user desktop host, but it
# cannot represent two concurrent sessions (e.g. two projects at once). A second
# start_session while one is active is refused by _active_session_error(); real
# multi-session support needs a registry keyed by project, not this dict.
_ACTIVE: dict[str, baseline.HumanBaselineSession | None] = {"session": None}


@app.action(id="hello", title="Hello")
def hello(_ctx: PluginContext, name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}!"


def _task_dir(base_dir: str) -> str:
    return base_dir or os.environ.get("EXPERIMENT_TASK_DIR") or "experiment/tasks"


def _active_session_error() -> str | None:
    active = _ACTIVE["session"]
    if active is None:
        return None
    started = active.started_at.isoformat()
    return f"session already active for {active.task_id} — end it first (started {started})"


def _log_capped(
    session: baseline.HumanBaselineSession, event: str, tool: str, **fields: object
) -> None:
    """Log HOST event unless the per-session event cap is reached."""
    if session.tracker.event_count < MAX_EVENTS:
        session.log(event, tool=tool, **fields)  # type: ignore[arg-type]


def _wire_project_hooks(session: baseline.HumanBaselineSession, project: object) -> None:
    def layers_added(layers: object) -> None:
        count = len(layers or [])  # type: ignore[arg-type]
        _log_capped(session, "layers_added", "host:project", count=count)

    def layers_removed(ids: object) -> None:
        count = len(ids or [])  # type: ignore[arg-type]
        _log_capped(session, "layers_removed", "host:project", count=count)

    def crs_changed() -> None:
        crs = project.crs().authid()  # type: ignore[attr-defined]
        _log_capped(session, "crs_changed", "host:project", crs=crs)

    def project_read() -> None:
        _log_capped(session, "project_read", "host:project", path=project.fileName())  # type: ignore[attr-defined]

    project.layersAdded.connect(layers_added)  # type: ignore[attr-defined]
    project.layersWillBeRemoved.connect(layers_removed)  # type: ignore[attr-defined]
    project.crsChanged.connect(crs_changed)  # type: ignore[attr-defined]
    project.projectRead.connect(project_read)  # type: ignore[attr-defined]


def _wire_canvas_hooks(session: baseline.HumanBaselineSession, canvas: object) -> None:
    def extents_changed() -> None:
        extent = canvas.extent()  # type: ignore[attr-defined]
        _log_capped(
            session,
            "canvas_extent",
            "host:canvas",
            extent={
                "xmin": extent.xMinimum(),
                "ymin": extent.yMinimum(),
                "xmax": extent.xMaximum(),
                "ymax": extent.yMaximum(),
            },
        )

    def scale_changed(scale: float) -> None:
        _log_capped(session, "canvas_scale", "host:canvas", scale=scale)

    canvas.extentsChanged.connect(extents_changed)  # type: ignore[attr-defined]
    canvas.scaleChanged.connect(scale_changed)  # type: ignore[attr-defined]


def _connect_host_hooks(session: baseline.HumanBaselineSession) -> tuple[list[str], list[str]]:
    """Best-effort QGIS host hooks. Returns (connected, failures) — never silent."""
    connected: list[str] = []
    failures: list[str] = []
    try:
        from qgis.core import QgsProject

        _wire_project_hooks(session, QgsProject.instance())
        connected.append("project")
    except Exception as exc:  # host hooks are best-effort; report instead of crashing
        failures.append(f"project: {exc}")
    try:
        from qgis.utils import iface

        canvas = iface.mapCanvas() if iface is not None else None
        if canvas is not None:
            _wire_canvas_hooks(session, canvas)
            connected.append("canvas")
    except Exception as exc:  # host hooks are best-effort; report instead of crashing
        failures.append(f"canvas: {exc}")
    return connected, failures


def _start_message(
    session: baseline.HumanBaselineSession, hooks: list[str], failures: list[str]
) -> str:
    lines = [
        f"session started for task {session.task_id}",
        f"output dir: {session.output_dir}",
        f"task file sha256: {baseline.sha256_file(session.task_yaml)}",
        f"fixture sha256: {baseline.sha256_file(session.fixture)}",
        f"host hooks: {', '.join(hooks) if hooks else 'none (standalone host)'}",
    ]
    lines.extend(f"host hook failed: {failure}" for failure in failures)
    lines.append("timer started; click End human-baseline session when done")
    return "\n".join(lines)


@app.action(id="start_session", title="Start human-baseline session")
def start_session(
    _ctx: PluginContext,
    task_id: str = DEFAULT_TASK_ID,
    base_dir: str = "",
    participant_code: str = "",
) -> str:
    """Start recording a human-baseline session for TASK_ID.

    Fetches metadata automatically (hashes, software versions, UTC start
    time), creates the gitignored per-session baseline directory and starts
    the event log. The record's network_disabled stays null (host cannot
    verify it). Failures are plain text mixed into the success output —
    fine for a desktop action label; do not parse it.
    """
    if (error := _active_session_error()) is not None:
        return error
    root = _task_dir(base_dir)
    try:
        session = baseline.start_session(
            task_id,
            root,
            participant_code=participant_code or None,
        )
    except (FileNotFoundError, KeyError) as exc:
        return f"cannot start session: {exc}"
    hooks, failures = _connect_host_hooks(session)
    _ACTIVE["session"] = session
    return _start_message(session, hooks, failures)


@app.action(id="log_note", title="Log session note")
def log_note(_ctx: PluginContext, message: str) -> str:
    """Record a note/deviation/interruption in the active session's event log."""
    session = _ACTIVE["session"]
    if session is None:
        return "no active session"
    session.log("note", tool="note", message=message)
    return f"note recorded ({session.tracker.event_count} events so far)"


@app.action(id="end_session", title="End human-baseline session")
def end_session(_ctx: PluginContext) -> str:
    """Stop the timer, hash outputs, write human-reference-record.json."""
    session = _ACTIVE["session"]
    if session is None:
        return "no active session"
    record_path = session.finish()
    _ACTIVE["session"] = None
    lines = [
        f"session ended for {session.task_id}",
        f"events: {session.tracker.event_count}  tools: {', '.join(session.tools_used) or 'none'}",
        f"record written: {record_path}",
        "next: pixi run experiment pilot determinism "
        f"{session.task_id} --artifacts-dir {session.output_dir}",
        "note: task YAML human_baseline.status stays 'pending' until you review it",
    ]
    return "\n".join(lines)
