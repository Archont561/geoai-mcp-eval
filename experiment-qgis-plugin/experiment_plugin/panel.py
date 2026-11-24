"""Non-modal tabbed QGIS session panel (Timer + Logs) for human-baseline runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from qgis_sdk.ui.surfaces import Dialog

from experiment_plugin import _state
from experiment_plugin import session as baseline

_K_STATUS = "status_label"
_K_ELAPSED = "elapsed_label"
_K_TASK = "task_edit"
_K_PARTICIPANT = "participant_edit"
_K_TABS = "tabs"


def exception_detail(error: BaseException) -> str:
    """Format an exception (or ExceptionGroup) into a readable single-line detail."""
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(exception_detail(child) for child in error.exceptions)
    return str(error)


def format_elapsed(seconds: float) -> str:
    """Format an elapsed duration as HH:MM:SS (hours may exceed 23)."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _labeled_input(label_text: str, object_name: str, default: str = "") -> tuple[object, object]:
    from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QLineEdit

    row = QHBoxLayout()
    row.addWidget(QLabel(label_text))
    field = QLineEdit(default)
    field.setObjectName(object_name)
    row.addWidget(field)
    return row, field


def _button_row(specs: tuple[tuple[str, str, str], ...]) -> tuple[object, dict[str, object]]:
    from qgis.PyQt.QtWidgets import QHBoxLayout, QPushButton

    row = QHBoxLayout()
    buttons: dict[str, object] = {}
    for key, text, obj_name in specs:
        btn = QPushButton(text)
        btn.setObjectName(obj_name)
        row.addWidget(btn)
        buttons[key] = btn
    return row, buttons


def _timer_labels() -> tuple[object, object]:
    from qgis.PyQt.QtWidgets import QLabel

    status_label = QLabel("no active session")
    elapsed_label = QLabel("--:--:--")
    elapsed_label.setStyleSheet("font-size: 28px; font-family: monospace;")
    return status_label, elapsed_label


def _timer_controls(task_default: str) -> tuple[list[object], list[object], dict]:
    task_row, task_edit = _labeled_input("Task id:", "sessionTaskEdit", task_default)
    part_row, participant_edit = _labeled_input("Participant (optional):", "sessionParticipantEdit")
    status_label, elapsed_label = _timer_labels()
    btn_row, buttons = _button_row(
        (
            ("start_button", "Start", "sessionStartButton"),
            ("stop_button", "Stop", "sessionStopButton"),
            ("restart_button", "Restart", "sessionRestartButton"),
        )
    )
    parts = {
        _K_TASK: task_edit,
        _K_PARTICIPANT: participant_edit,
        _K_STATUS: status_label,
        _K_ELAPSED: elapsed_label,
        **buttons,
    }
    return [task_row, part_row, btn_row], [status_label, elapsed_label], parts


def _build_timer_page(task_default: str) -> tuple[object, dict]:
    from qgis.PyQt.QtWidgets import QVBoxLayout, QWidget

    page = QWidget()
    layout = QVBoxLayout(page)
    rows, labels, parts = _timer_controls(task_default)
    layout.addLayout(rows[0])
    layout.addLayout(rows[1])
    layout.addWidget(labels[0])
    layout.addWidget(labels[1])
    layout.addLayout(rows[2])
    return page, parts


def _build_logs_page() -> tuple[object, dict]:
    from qgis.PyQt.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

    page = QWidget()
    layout = QVBoxLayout(page)
    log_header = QLabel("no session yet")
    layout.addWidget(log_header)
    log_edit = QPlainTextEdit()
    log_edit.setObjectName("sessionLogEdit")
    log_edit.setReadOnly(True)
    layout.addWidget(log_edit)
    btn_row, buttons = _button_row(
        (
            ("refresh_button", "Refresh", "sessionRefreshButton"),
            ("export_button", "Export…", "sessionExportButton"),
        )
    )
    layout.addLayout(btn_row)
    return page, {"log_header": log_header, "log_edit": log_edit, **buttons}


def _start_timer(parent: object, interval_ms: int, callback: object) -> None:
    from qgis.PyQt.QtCore import QTimer

    timer = QTimer(parent)
    timer.timeout.connect(callback)
    timer.setInterval(interval_ms)
    timer.start()


def _confirm_restart(parent: object) -> bool:
    from qgis.PyQt.QtWidgets import QMessageBox

    answer = QMessageBox.question(
        parent,
        "Restart session",
        "Abandon the current session?\n"
        "Evidence stays on disk and is marked abandoned;\n"
        "the human-reference-record is NOT written.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def _export_session_log(parent: object, session: baseline.HumanBaselineSession) -> str:
    from qgis.PyQt.QtWidgets import QFileDialog

    text = baseline.render_log(session)
    default_name = f"{session.output_dir.name}-events.txt"
    path, _selected = QFileDialog.getSaveFileName(
        parent,
        "Export session log",
        str(Path.home() / default_name),
        "Text files (*.txt)",
    )
    if not path:
        return "export cancelled"
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"export failed: {exc}"
    return f"log exported to {path}"


class SessionPanelDialog(Dialog):
    """Non-modal tabbed panel for the human-baseline session (Timer + Logs)."""

    title = "Human-baseline session"

    def _call_action(self, name: str, **kwargs: object) -> str:
        result, _succeeded = self._dispatch_action(name, **kwargs)
        return result

    def _dispatch_action(self, name: str, **kwargs: object) -> tuple[str, bool]:
        ctx = self.ctx
        try:
            if callable(getattr(ctx, "has", None)) and not ctx.has("actions"):
                return "no actions capability in this host (a GUI host is required)", False
            actions = ctx.actions
        except Exception as exc:
            return f"actions unavailable: {exc}", False
        handler = getattr(actions, name, None)
        if handler is None:
            return f"unknown action {name}", False
        try:
            return str(handler(**kwargs)), True
        except Exception as exc:
            return f"{name} failed: {exception_detail(exc)}", False

    @staticmethod
    def _current_session() -> baseline.HumanBaselineSession | None:
        return _state.ACTIVE[_state.SESSION_KEY] or _state.LAST[_state.SESSION_KEY]

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
        session = _state.ACTIVE[_state.SESSION_KEY]
        active = session is not None
        parts["start_button"].setEnabled(not active)
        parts["stop_button"].setEnabled(active)
        parts["restart_button"].setEnabled(active)
        parts[_K_TASK].setEnabled(not active)
        parts[_K_PARTICIPANT].setEnabled(not active)
        if active:
            assert session is not None
            parts[_K_TASK].setText(session.task_id)
            parts[_K_PARTICIPANT].setText(session.participant_code or "")
            parts[_K_STATUS].setText(f"recording — {session.task_id}")
            return
        parts[_K_STATUS].setText("no active session")
        parts[_K_ELAPSED].setText("--:--:--")

    def _tick(self) -> None:
        session = _state.ACTIVE[_state.SESSION_KEY]
        if session is None:
            self._parts[_K_ELAPSED].setText("--:--:--")
            return
        elapsed = datetime.now(UTC) - session.started_at
        self._parts[_K_ELAPSED].setText(format_elapsed(elapsed.total_seconds()))

    def _params(self) -> tuple[str, str]:
        task_id = self._parts[_K_TASK].text().strip() or _state.DEFAULT_TASK_ID
        return task_id, self._parts[_K_PARTICIPANT].text().strip()

    def _after_change(self, result: str, fallback: str) -> None:
        self._refresh_controls()
        self._refresh_logs()
        self._tick()
        lines = result.splitlines()
        summary = lines[0] if lines else fallback
        hook_failures = [line for line in lines[1:] if line.startswith("host hook failed:")]
        self._parts[_K_STATUS].setText("\n".join([summary, *hook_failures]))

    def _on_start(self) -> None:
        task_id, participant = self._params()
        result = self._call_action(
            "start_session", task_id=task_id, base_dir="", participant_code=participant
        )
        self._after_change(result, "session started")

    def _on_stop(self) -> None:
        frozen = self._parts[_K_ELAPSED].text()
        result = self._call_action("end_session")
        self._refresh_controls()
        self._parts[_K_ELAPSED].setText(frozen)
        self._refresh_logs()
        self._parts[_K_STATUS].setText(result.splitlines()[0] if result else "session ended")

    def _on_restart(self) -> None:
        if not _confirm_restart(self._parts[_K_TABS]):
            self._parts[_K_STATUS].setText("restart cancelled")
            return
        task_id, participant = self._params()
        previous = _state.ACTIVE[_state.SESSION_KEY]
        result, succeeded = self._dispatch_action("abandon_session")
        if not succeeded or previous is None or previous.status != "abandoned":
            self._after_change(result, "restart failed")
            return
        result = self._call_action(
            "start_session", task_id=task_id, base_dir="", participant_code=participant
        )
        self._after_change(result, "session restarted")

    def _on_export(self) -> None:
        session = self._current_session()
        if session is None:
            self._parts[_K_STATUS].setText("no session to export")
            return
        status = _export_session_log(self._parts[_K_TABS], session)
        self._parts[_K_STATUS].setText(status)

    def _wire(self, timer_page: object, logs_page: object) -> None:
        parts = self._parts
        parts["start_button"].clicked.connect(self._on_start)
        parts["stop_button"].clicked.connect(self._on_stop)
        parts["restart_button"].clicked.connect(self._on_restart)
        parts["refresh_button"].clicked.connect(self._refresh_logs)
        parts["export_button"].clicked.connect(self._on_export)
        _start_timer(timer_page, 1000, self._tick)
        _start_timer(logs_page, 2000, self._refresh_logs)

    def build(self):
        """Return the tabbed widget; the one Qt-touching hook, run inside QGIS."""
        from qgis.PyQt.QtWidgets import QTabWidget

        task_default = str(self.initial.get("task_id") or _state.DEFAULT_TASK_ID)
        timer_page, timer_parts = _build_timer_page(task_default)
        logs_page, logs_parts = _build_logs_page()
        tabs = QTabWidget()
        tabs.setObjectName("sessionTabs")
        tabs.addTab(timer_page, "Timer")
        tabs.addTab(logs_page, "Logs")
        self._parts = {**timer_parts, **logs_parts, _K_TABS: tabs}
        self._wire(timer_page, logs_page)
        self._refresh_controls()
        self._refresh_logs()
        self._tick()
        return tabs
