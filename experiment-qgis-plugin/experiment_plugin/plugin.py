"""Experiment Plugin: human-baseline session recorder (plus hello demo)."""

from __future__ import annotations

import os
from pathlib import Path

from qgis_sdk import QgisSdkPlugin, menu
from qgis_sdk.core import PluginContext

from experiment_plugin import _state, host_observation, panel
from experiment_plugin import review as session_review
from experiment_plugin import session as baseline

# Re-export compatibility helpers expected by tests and callers.
MAX_EVENTS = host_observation.MAX_EVENTS
_log_capped = host_observation.log_capped
_wire_canvas_hooks = host_observation.wire_canvas_hooks
_wire_project_hooks = host_observation.wire_project_hooks
_connect_host_hooks = host_observation.connect_host_hooks
_format_elapsed = panel.format_elapsed
SessionPanelDialog = panel.SessionPanelDialog

DEFAULT_TASK_ID = _state.DEFAULT_TASK_ID
_ACTIVE = _state.ACTIVE
_LAST = _state.LAST
_K_SESSION = _state.SESSION_KEY
_K_RESOURCES = "resources"

app = QgisSdkPlugin(id="experiment_plugin", title="Experiment Plugin")


class _SessionResources:
    """Tie one session's host hooks to the plugin's SDK lifetime."""

    def __init__(self, session: baseline.HumanBaselineSession, ctx: PluginContext | None) -> None:
        self.session = session
        self.hooks = host_observation.HostHooks()
        self.scope = ctx.scope.child() if ctx is not None else None
        if self.scope is not None:
            self.scope.on_close(self._on_scope_close)

    def close(self) -> None:
        if self.scope is not None:
            self.scope.close()
        else:
            self._on_scope_close()

    def _abandon_if_active(self) -> BaseException | None:
        active = _ACTIVE[_K_SESSION] is self.session
        failure: BaseException | None = None
        try:
            if active:
                baseline.abandon_session(self.session, reason="plugin unloaded")
        except BaseException as exc:
            self.session.status = "incomplete"
            failure = exc
        finally:
            if active:
                _LAST[_K_SESSION] = self.session
                _ACTIVE[_K_SESSION] = None
            if _state.RUNTIME[_K_RESOURCES] is self:
                _state.RUNTIME[_K_RESOURCES] = None
        return failure

    def _on_scope_close(self) -> None:
        self.hooks.pause()
        failure = self._abandon_if_active()
        try:
            self.hooks.close()
        except BaseException as cleanup_error:
            if failure is not None:
                raise BaseExceptionGroup(
                    "abandonment and cleanup failed", [failure, cleanup_error]
                ) from None
            raise
        if failure is not None:
            raise failure


app.add_surface(SessionPanelDialog)


@app.action(id="hello", title="Hello")
def hello(_ctx: PluginContext, name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}!"


def _task_dir(base_dir: str) -> str:
    explicit = base_dir.strip()
    if explicit:
        return explicit
    from_env = (os.environ.get("EXPERIMENT_TASK_DIR") or "").strip()
    if from_env:
        return from_env
    return str(baseline.discover_task_dir())


def _active_session_error() -> str | None:
    active = _ACTIVE[_K_SESSION]
    if active is None:
        return None
    started = active.started_at.isoformat()
    return f"session already active for {active.task_id} — end it first (started {started})"


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


def _activate_session(session: baseline.HumanBaselineSession, ctx: PluginContext) -> str:
    resources = _SessionResources(session, ctx)
    _state.RUNTIME[_K_RESOURCES] = resources
    _ACTIVE[_K_SESSION] = session
    try:
        hooks, failures = _connect_host_hooks(session, resources.hooks)
        session.set_hook_status(hooks, failures, processing_connected="processing" in hooks)
        return _start_message(session, hooks, failures)
    except BaseException as error:
        _retire_failed_session(session, resources, error, "starting")
        raise


@app.action(id="start_session", title="Start human-baseline session")
def start_session(
    _ctx: PluginContext,
    task_id: str = DEFAULT_TASK_ID,
    base_dir: str = "",
    participant_code: str = "",
) -> str:
    """Start recording a human-baseline session for TASK_ID."""
    if (error := _active_session_error()) is not None:
        return error
    try:
        session = baseline.start_session(
            task_id, _task_dir(base_dir), participant_code=participant_code or None
        )
    except (FileNotFoundError, KeyError) as exc:
        return f"cannot start session: {exc}"
    return _activate_session(session, _ctx)


@menu("Plugins/Experiment Plugin")
@app.action(id="show_timer", title="Show session panel")
def show_timer(ctx: PluginContext) -> str:
    """Open the tabbed session panel (Timer tab + Logs tab)."""
    session_ = _ACTIVE[_K_SESSION]
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
        initial={"started_at": session_.started_at.isoformat(), "task_id": session_.task_id},
    )
    return f"session panel opened for task {session_.task_id}"


@app.action(id="log_note", title="Log session note")
def log_note(_ctx: PluginContext, message: str) -> str:
    """Record a note/deviation/interruption in the active session's event log."""
    session = _ACTIVE[_K_SESSION]
    if session is None:
        return "no active session"
    session.log("note", source="note", message=message)
    return f"note recorded ({session.tracker.event_count} events so far)"


@app.action(id="log_manual_action", title="Log manual action group")
def log_manual_action(_ctx: PluginContext, action_group: str, tool: str = "") -> str:
    """Record one manually identified GIS action group without fabricating a tool."""
    session = _ACTIVE[_K_SESSION]
    if session is None:
        return "no active session"
    try:
        session.record_manual_action_group(action_group, tool=tool or None)
    except ValueError:
        return "manual action group description is required"
    count = len(session.metrics.manual_action_groups)
    return f"manual action group recorded ({count} manual groups so far)"


def _retire_session(
    session: baseline.HumanBaselineSession, resources: _SessionResources | None
) -> None:
    _LAST[_K_SESSION] = session
    _ACTIVE[_K_SESSION] = None
    _state.RUNTIME[_K_RESOURCES] = None
    if resources is not None:
        resources.close()


def _retire_failed_session(
    session: baseline.HumanBaselineSession,
    resources: _SessionResources | None,
    error: BaseException,
    operation: str,
) -> None:
    session.status = "incomplete"
    try:
        _retire_session(session, resources)
    except BaseException as cleanup_error:
        raise BaseExceptionGroup(
            f"{operation} and cleanup failed", [error, cleanup_error]
        ) from None


@app.action(id="abandon_session", title="Abandon human-baseline session")
def abandon_session(_ctx: PluginContext) -> str:
    """Abandon the active session WITHOUT writing human-reference-record.json."""
    session = _ACTIVE[_K_SESSION]
    if session is None:
        return "no active session"
    resources: _SessionResources | None = _state.RUNTIME[_K_RESOURCES]
    if resources is not None:
        resources.hooks.pause()
    try:
        marker = baseline.abandon_session(session)
    except BaseException as error:
        _retire_failed_session(session, resources, error, "abandonment")
        raise
    _retire_session(session, resources)
    return (
        f"session abandoned for {session.task_id} — no record written; evidence marked at {marker}"
    )


def _metrics_summary_line(
    session: baseline.HumanBaselineSession, *, manual_review_complete: bool
) -> str:
    steps, tools, metrics_status, _detail = session.metrics.build_summary(
        manual_review_complete=manual_review_complete
    )
    if metrics_status == baseline.MetricsStatus.REVIEWED:
        tool_text = ", ".join(tools or []) or "none"
        return (
            f"events: {session.tracker.event_count}  steps: {steps}  tools: {tool_text} (reviewed)"
        )
    return (
        f"events: {session.tracker.event_count}  "
        f"observations: {session.metrics.raw_event_count}  metrics: pending review"
    )


def _file_size_or_none(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _finish_or_recover(
    session: baseline.HumanBaselineSession,
    resources: _SessionResources | None,
    *,
    manual_review_complete: bool,
) -> Path:
    events_path = session.tracker.events_path
    log_size = _file_size_or_none(events_path)
    try:
        return session.finish(manual_review_complete=manual_review_complete)
    except BaseException as error:
        current_size = _file_size_or_none(events_path)
        can_resume = (
            log_size is not None
            and current_size == log_size
            and not isinstance(error, BaseExceptionGroup)
        )
        if can_resume:
            if resources is not None:
                resources.hooks.resume()
        else:
            _retire_failed_session(session, resources, error, "ending")
        raise


@app.action(id="end_session", title="End human-baseline session")
def end_session(_ctx: PluginContext, manual_review_complete: bool = False) -> str:
    """Stop the timer, hash outputs, write human-reference-record.json."""
    session = _ACTIVE[_K_SESSION]
    if session is None:
        return "no active session"
    resources: _SessionResources | None = _state.RUNTIME[_K_RESOURCES]
    if resources is not None:
        resources.hooks.pause()
    record_path = _finish_or_recover(
        session, resources, manual_review_complete=manual_review_complete
    )
    _retire_session(session, resources)
    return "\n".join(
        [
            f"session ended for {session.task_id}",
            _metrics_summary_line(session, manual_review_complete=manual_review_complete),
            f"record written: {record_path}",
            "next: pixi run experiment pilot determinism "
            f"{session.task_id} --artifacts-dir {session.output_dir}",
            "note: task YAML human_baseline.status stays 'pending' until you review it",
        ]
    )


@app.action(id="review_session", title="Review recorded human-baseline session")
def review_session(  # noqa: CC102
    _ctx: PluginContext,
    session_dir: str,
    manual_actions: list[session_review.ReviewActionInput] | None = None,
    mark_reviewed: bool = False,
    reviewer: str = "",
    notes: str = "",
    processing_log: str = "",
    output_dir: str = "",
) -> str:
    """Audit a completed session take and emit separate reviewed artifacts."""
    try:
        result = session_review.review_session(
            session_dir,
            manual_actions=manual_actions or (),
            mark_reviewed=mark_reviewed,
            reviewer=reviewer or None,
            notes=notes or None,
            processing_log=processing_log or None,
            output_dir=output_dir or None,
        )
    except (session_review.ReviewError, ValueError) as exc:
        return f"cannot review session: {exc}"
    return session_review.format_review_summary(result)
