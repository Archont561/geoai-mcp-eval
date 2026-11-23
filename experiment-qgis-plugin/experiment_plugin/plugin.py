"""Experiment Plugin: human-baseline session recorder (plus hello demo)."""

from __future__ import annotations

import os

from qgis_sdk import QgisSdkPlugin, menu
from qgis_sdk.core import PluginContext
from qgis_sdk.ui.surfaces import Dialog

from experiment_plugin import session as baseline

MAX_EVENTS = 2000
DEFAULT_TASK_ID = "prep-axis-order-001"

app = QgisSdkPlugin(id="experiment_plugin", title="Experiment Plugin")

# Single active session: the right shape for a single-user desktop host, but it
# cannot represent two concurrent sessions (e.g. two projects at once). A second
# start_session while one is active is refused by _active_session_error(); real
# multi-session support needs a registry keyed by project, not this dict.
_ACTIVE: dict[str, baseline.HumanBaselineSession | None] = {"session": None}

# The last session to reach a terminal state (ended or abandoned). The
# panel's Logs tab and Export keep showing it once _ACTIVE is cleared.
_LAST: dict[str, baseline.HumanBaselineSession | None] = {"session": None}


def _format_elapsed(seconds: float) -> str:
    """Format an elapsed duration as HH:MM:SS (hours may exceed 23)."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class SessionPanelDialog(Dialog):
    """Non-modal tabbed panel for the human-baseline session.

    Tab "Timer": task/participant fields, a HH:MM:SS counter and Start / Stop /
    Restart buttons that drive the actual session, not just the display.
    Start creates the session (same path as the ``start_session`` action); Stop
    ends it and writes the record; Restart abandons the current session
    (evidence kept on disk and marked abandoned, NO human-reference-record is
    written) and starts a fresh one with the same parameters — only after a
    confirmation. Tab "Logs": a live, auto-refreshing rendering of the active
    (or most recently ended/abandoned) session's event log, with Refresh and
    Export buttons; Export writes the same rendering to a file you choose.

    Closing the window only stops the display; the recording is unaffected.
    ``initial`` carries ``started_at`` (ISO 8601) and ``task_id``, handed over
    by the ``show_timer`` action. Actions are reached as ``self.ctx.actions``
    (decision-55); when a host provides no actions capability the panel says
    so instead of raising.
    """

    title = "Human-baseline session"

    def _call_action(self, name: str, **kwargs: object) -> str:
        """Call one of the plugin's own actions via the view's dispatcher."""
        ctx = self.ctx
        try:
            if callable(getattr(ctx, "has", None)) and not ctx.has("actions"):
                return "no actions capability in this host (a GUI host is required)"
            actions = ctx.actions
        except Exception as exc:
            return f"actions unavailable: {exc}"
        handler = getattr(actions, name, None)
        if handler is None:
            return f"unknown action {name}"
        try:
            result = handler(**kwargs)
        except Exception as exc:
            return f"{name} failed: {exc}"
        return str(result)

    # -- panel construction (Qt imports stay inside the methods) -----------

    @staticmethod
    def _current_session() -> baseline.HumanBaselineSession | None:
        return _ACTIVE["session"] or _LAST["session"]

    def _build_timer_page(self, task_default: str) -> tuple[object, dict]:
        from qgis.PyQt.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        page = QWidget()
        layout = QVBoxLayout(page)

        task_row = QHBoxLayout()
        task_row.addWidget(QLabel("Task id:"))
        task_edit = QLineEdit(task_default)
        task_edit.setObjectName("sessionTaskEdit")
        task_row.addWidget(task_edit)
        layout.addLayout(task_row)

        participant_row = QHBoxLayout()
        participant_row.addWidget(QLabel("Participant (optional):"))
        participant_edit = QLineEdit()
        participant_edit.setObjectName("sessionParticipantEdit")
        participant_row.addWidget(participant_edit)
        layout.addLayout(participant_row)

        status_label = QLabel("no active session")
        layout.addWidget(status_label)
        elapsed_label = QLabel("--:--:--")
        elapsed_label.setStyleSheet("font-size: 28px; font-family: monospace;")
        layout.addWidget(elapsed_label)

        button_row = QHBoxLayout()
        start_button = QPushButton("Start")
        start_button.setObjectName("sessionStartButton")
        stop_button = QPushButton("Stop")
        stop_button.setObjectName("sessionStopButton")
        restart_button = QPushButton("Restart")
        restart_button.setObjectName("sessionRestartButton")
        button_row.addWidget(start_button)
        button_row.addWidget(stop_button)
        button_row.addWidget(restart_button)
        layout.addLayout(button_row)

        return page, {
            "task_edit": task_edit,
            "participant_edit": participant_edit,
            "status_label": status_label,
            "elapsed_label": elapsed_label,
            "start_button": start_button,
            "stop_button": stop_button,
            "restart_button": restart_button,
        }

    def _build_logs_page(self) -> tuple[object, dict]:
        from qgis.PyQt.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QPlainTextEdit,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        page = QWidget()
        layout = QVBoxLayout(page)
        log_header = QLabel("no session yet")
        layout.addWidget(log_header)
        log_edit = QPlainTextEdit()
        log_edit.setObjectName("sessionLogEdit")
        log_edit.setReadOnly(True)
        layout.addWidget(log_edit)
        button_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("sessionRefreshButton")
        export_button = QPushButton("Export…")
        export_button.setObjectName("sessionExportButton")
        button_row.addWidget(refresh_button)
        button_row.addWidget(export_button)
        layout.addLayout(button_row)

        return page, {
            "log_header": log_header,
            "log_edit": log_edit,
            "refresh_button": refresh_button,
            "export_button": export_button,
        }

    def _refresh_logs(self) -> None:
        parts = self._parts
        session = self._current_session()
        if session is None:
            parts["log_header"].setText("no session yet")
            parts["log_edit"].setPlainText("")
            return
        parts["log_header"].setText(f"{session.task_id} — {session.output_dir} ({session.status})")
        parts["log_edit"].setPlainText(baseline.render_log(session))

    def _refresh_controls(self) -> None:
        parts = self._parts
        session = _ACTIVE["session"]
        active = session is not None
        parts["start_button"].setEnabled(not active)
        parts["stop_button"].setEnabled(active)
        parts["restart_button"].setEnabled(active)
        parts["task_edit"].setEnabled(not active)
        parts["participant_edit"].setEnabled(not active)
        if active:
            assert session is not None
            parts["task_edit"].setText(session.task_id)
            parts["participant_edit"].setText(session.participant_code or "")
            parts["status_label"].setText(f"recording — {session.task_id}")
            return
        parts["status_label"].setText("no active session")
        parts["elapsed_label"].setText("--:--:--")

    def _tick(self) -> None:
        from datetime import UTC, datetime

        parts = self._parts
        session = _ACTIVE["session"]
        if session is None:
            parts["elapsed_label"].setText("--:--:--")
            return
        elapsed = datetime.now(UTC) - session.started_at
        parts["elapsed_label"].setText(_format_elapsed(elapsed.total_seconds()))

    def _params(self) -> tuple[str, str]:
        parts = self._parts
        task_id = parts["task_edit"].text().strip() or DEFAULT_TASK_ID
        return task_id, parts["participant_edit"].text().strip()

    def _after_change(self, result: str, fallback: str) -> None:
        self._refresh_controls()
        self._refresh_logs()
        self._tick()
        self._parts["status_label"].setText(result.splitlines()[0] if result else fallback)

    def _on_start(self) -> None:
        task_id, participant = self._params()
        result = self._call_action(
            "start_session",
            task_id=task_id,
            base_dir="",
            participant_code=participant,
        )
        self._after_change(result, "session started")

    def _on_stop(self) -> None:
        frozen = self._parts["elapsed_label"].text()
        result = self._call_action("end_session")
        self._refresh_controls()
        self._parts["elapsed_label"].setText(frozen)  # keep the final reading
        self._refresh_logs()
        self._parts["status_label"].setText(result.splitlines()[0] if result else "session ended")

    def _on_restart(self) -> None:
        from qgis.PyQt.QtWidgets import QMessageBox

        yes = QMessageBox.StandardButton.Yes
        answer = QMessageBox.question(
            self._parts["tabs"],
            "Restart session",
            "Abandon the current session?\n"
            "Evidence stays on disk and is marked abandoned;\n"
            "the human-reference-record is NOT written.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != yes:
            self._parts["status_label"].setText("restart cancelled")
            return
        task_id, participant = self._params()
        self._call_action("abandon_session")
        result = self._call_action(
            "start_session",
            task_id=task_id,
            base_dir="",
            participant_code=participant,
        )
        self._after_change(result, "session restarted")

    def _on_export(self) -> None:
        from pathlib import Path

        from qgis.PyQt.QtWidgets import QFileDialog

        session = self._current_session()
        if session is None:
            self._parts["status_label"].setText("no session to export")
            return
        text = baseline.render_log(session)
        default_name = f"{session.output_dir.name}-events.txt"
        path, _selected = QFileDialog.getSaveFileName(
            self._parts["tabs"],
            "Export session log",
            str(Path.home() / default_name),
            "Text files (*.txt)",
        )
        if not path:
            self._parts["status_label"].setText("export cancelled")
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            self._parts["status_label"].setText(f"export failed: {exc}")
            return
        self._parts["status_label"].setText(f"log exported to {path}")

    def _wire(self, tick_timer_parent: object, log_timer_parent: object, logs_page: object) -> None:
        from qgis.PyQt.QtCore import QTimer

        parts = self._parts
        parts["start_button"].clicked.connect(self._on_start)
        parts["stop_button"].clicked.connect(self._on_stop)
        parts["restart_button"].clicked.connect(self._on_restart)
        parts["refresh_button"].clicked.connect(self._refresh_logs)
        parts["export_button"].clicked.connect(self._on_export)

        tick_timer = QTimer(tick_timer_parent)
        tick_timer.timeout.connect(self._tick)
        tick_timer.setInterval(1000)
        tick_timer.start()

        log_timer = QTimer(logs_page)
        log_timer.timeout.connect(self._refresh_logs)
        log_timer.setInterval(2000)
        log_timer.start()

    def build(self):
        """Return the tabbed widget; the one Qt-touching hook, run inside QGIS."""
        from qgis.PyQt.QtWidgets import QTabWidget

        task_default = str(self.initial.get("task_id") or DEFAULT_TASK_ID)
        timer_page, timer_parts = self._build_timer_page(task_default)
        logs_page, logs_parts = self._build_logs_page()
        tabs = QTabWidget()
        tabs.setObjectName("sessionTabs")
        tabs.addTab(timer_page, "Timer")
        tabs.addTab(logs_page, "Logs")
        self._parts = {**timer_parts, **logs_parts, "tabs": tabs}
        self._wire(timer_page, logs_page, logs_page)
        self._refresh_controls()
        self._refresh_logs()
        self._tick()
        return tabs


app.add_surface(SessionPanelDialog)


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


def _wire_project_hooks(session: baseline.HumanBaselineSession, project: object) -> list[str]:
    """Wire project hooks. Returns a list of non-fatal warnings (empty if all wired)."""
    warnings: list[str] = []

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
        path = project.fileName()  # type: ignore[attr-defined]
        _log_capped(session, "project_read", "host:project", path=path)

    # QGIS 4 renamed the project-read signal: projectRead -> readProject
    # (PyQt bound signal in both). Bind whichever exists so QGIS 3 and 4 hosts
    # both report hooks connected instead of silently failing the whole hook.
    def _connectable(name: str) -> object | None:
        candidate = getattr(project, name, None)
        if callable(candidate) and hasattr(candidate, "connect"):
            return candidate
        return None

    read_signal = next(
        (_connectable(name) for name in ("readProject", "projectRead") if _connectable(name)),
        None,
    )

    project.layersAdded.connect(layers_added)  # type: ignore[attr-defined]
    project.layersWillBeRemoved.connect(layers_removed)  # type: ignore[attr-defined]
    project.crsChanged.connect(crs_changed)  # type: ignore[attr-defined]
    if read_signal is not None:
        read_signal.connect(project_read)
    else:
        warnings.append("project_read: no project-read signal found (readProject/projectRead)")
    return warnings


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

        warnings = _wire_project_hooks(session, QgsProject.instance())
        connected.extend(["project"] if not warnings else ["project (partial)"])
        failures.extend(warnings)
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


@menu("Plugins/Experiment Plugin")
@app.action(id="show_timer", title="Show session panel")
def show_timer(ctx: PluginContext) -> str:
    """Open the tabbed session panel (Timer tab + Logs tab).

    The panel is a non-modal top-level window; opening it changes nothing
    about the recording — Stop inside the panel runs the end_session action
    and writes the record. With no active session the panel opens idle
    (Start button arms a fresh one). A host without a GUI (standalone runs,
    pure tests) answers with a message instead of raising.
    """
    session_ = _ACTIVE["session"]
    has = getattr(ctx, "has", None)
    ui = ctx.ui if callable(has) and has("ui") else None
    if ui is None:
        if session_ is None:
            return "no active session — start one first"
        return "session panel needs a GUI host (QGIS Desktop); this host has no ui capability"
    if session_ is None:
        ui.open(SessionPanelDialog, initial={})
        return "session panel opened (no active session yet — press Start)"
    ui.open(
        SessionPanelDialog,
        initial={
            "started_at": session_.started_at.isoformat(),
            "task_id": session_.task_id,
        },
    )
    return f"session panel opened for task {session_.task_id}"


@app.action(id="log_note", title="Log session note")
def log_note(_ctx: PluginContext, message: str) -> str:
    """Record a note/deviation/interruption in the active session's event log."""
    session = _ACTIVE["session"]
    if session is None:
        return "no active session"
    session.log("note", tool="note", message=message)
    return f"note recorded ({session.tracker.event_count} events so far)"


@app.action(id="abandon_session", title="Abandon human-baseline session")
def abandon_session(_ctx: PluginContext) -> str:
    """Abandon the active session WITHOUT writing human-reference-record.json.

    The event log stays on disk and gains a ``session_abandoned`` marker
    event; a ``session-abandoned.json`` marker is written next to it so the
    directory reads as an abandoned take. Nothing is promoted to reference
    evidence and the task YAML ``human_baseline.status`` is untouched.
    """
    session = _ACTIVE["session"]
    if session is None:
        return "no active session"
    marker = baseline.abandon_session(session)
    _LAST["session"] = session
    _ACTIVE["session"] = None
    return (
        f"session abandoned for {session.task_id} — no record written; evidence marked at {marker}"
    )


@app.action(id="end_session", title="End human-baseline session")
def end_session(_ctx: PluginContext) -> str:
    """Stop the timer, hash outputs, write human-reference-record.json."""
    session = _ACTIVE["session"]
    if session is None:
        return "no active session"
    record_path = session.finish()
    _LAST["session"] = session
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
