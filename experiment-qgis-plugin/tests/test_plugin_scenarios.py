"""Step definitions and scenario bindings for the plugin's Gherkin scenarios.

The scenarios live in ``experiment-qgis-plugin/features/``. Every step reaches
the plugin only through its public surface — ``runtime.actions`` and the real
``SessionPanelDialog`` — so a scenario failure means the plugin misbehaves for a
real host, not that an internal helper changed shape.

Steps and their ``scenarios()`` bindings share this one module deliberately:
pytest only parses a module's fixtures when it collects that module, so a
separate bindings module would be collected before the steps existed and every
scenario would fail with ``StepDefinitionNotFoundError``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plugin_harness import (
    DEMO_TASK_ID,
    FakeCanvas,
    FakeFileDialog,
    FakeHistoryRegistry,
    FakeMessageBox,
    FakeProject,
    FakeTimer,
    PluginHandle,
    install_host,
    read_events,
    read_record,
    remove_host,
    view_context,
)
from pytest_bdd import given, parsers, scenarios, then, when

from experiment_plugin import plugin

FEATURE_DIR = Path(__file__).resolve().parents[1] / "features"

# --- Given: the plugin -------------------------------------------------------


@given("the Experiment Plugin is loaded", target_fixture="loaded")
def the_plugin_is_loaded(session_store) -> PluginHandle:
    handle = PluginHandle()
    yield handle
    handle.unload()


@given("the pilot task suite is available")
def the_pilot_task_suite_is_available(pilot_tasks: Path) -> None:
    """The `pilot_tasks` fixture already provides the suite; this step documents it."""
    assert (pilot_tasks / "prep-axis-order-001.yaml").is_file()


@given("the Experiment Plugin is loaded with the pilot suite", target_fixture="loaded")
def the_plugin_is_loaded_with_pilot_suite(pilot_tasks) -> PluginHandle:
    handle = PluginHandle()
    yield handle
    handle.unload()


# --- When: the action surface ------------------------------------------------


@when(
    parsers.parse('I call the "{action}" action with name "{name}"'),
    target_fixture="reply",
)
def call_action_with_name(loaded: PluginHandle, action: str, name: str) -> str:
    return loaded.call(action, name=name)


@when('I call the "hello" action with no name', target_fixture="reply")
def call_action_without_name(loaded: PluginHandle) -> str:
    return loaded.call("hello", name="")


@when(
    parsers.parse('I call the undeclared action "{action_id}"'),
    target_fixture="error",
)
def call_undeclared_action(loaded: PluginHandle, action_id: str) -> Exception | None:
    try:
        loaded.call(action_id)
    except KeyError as exc:
        return exc
    return None


@when("the plugin unloads")
def the_plugin_unloads(loaded: PluginHandle) -> None:
    loaded.unload()


# --- Then: the action surface ------------------------------------------------


@then(parsers.parse('the action replies "{expected}"'))
def the_action_replies(reply: str, expected: str) -> None:
    assert reply == expected


@then(parsers.parse('the plugin offers the actions "{expected}"'))
def the_plugin_offers(loaded: PluginHandle, expected: str) -> None:
    assert ", ".join(sorted(loaded.actions)) == expected


@then("the call fails with a lookup error")
def the_call_fails_with_a_lookup_error(error: Exception | None) -> None:
    assert isinstance(error, KeyError)


@then(parsers.parse('the plugin registers a "{surface_id}" surface'))
def the_plugin_registers_a_surface(surface_id: str) -> None:
    from qgis_sdk import describe_bindings

    surfaces = [s.surface.id for s in describe_bindings(plugin.app).surfaces]
    assert surface_id in surfaces


@then("the plugin reports itself as stopped")
def the_plugin_reports_stopped(loaded: PluginHandle) -> None:
    assert loaded.plugin.runtime.state.value == "stopped"


# --- When: sessions ----------------------------------------------------------


def _start(loaded: PluginHandle, task_id: str, base_dir, **kwargs) -> str:
    return loaded.call("start_session", task_id=task_id, base_dir=str(base_dir), **kwargs)


@when(
    parsers.parse('I start a session for task "{task_id}"'),
    target_fixture="started",
)
def start_session(loaded: PluginHandle, pilot_tasks: Path, task_id: str) -> dict:
    reply = _start(loaded, task_id, pilot_tasks)
    recorder = plugin._ACTIVE["session"]
    return {
        "reply": reply,
        "output_dir": recorder.output_dir if recorder else None,
        "recorder": recorder,
    }


@when(
    parsers.parse('I log the note "{message}"'),
    target_fixture="reply",
)
def log_note(loaded: PluginHandle, message: str) -> str:
    return loaded.call("log_note", message=message)


@when("I end the session", target_fixture="reply")
def end_session(loaded: PluginHandle) -> str:
    return loaded.call("end_session")


@when("I end the session with manual review completed", target_fixture="reply")
def end_session_reviewed(loaded: PluginHandle) -> str:
    return loaded.call("end_session", manual_review_complete=True)


@when("I abandon the session", target_fixture="reply")
def abandon_session(loaded: PluginHandle) -> str:
    return loaded.call("abandon_session")


# --- Given: sessions ---------------------------------------------------------


@given("a session is active", target_fixture="running")
def a_session_is_active(loaded: PluginHandle, raw_task_suite) -> dict:
    _start(loaded, DEMO_TASK_ID, raw_task_suite)
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    return {"recorder": recorder, "output_dir": recorder.output_dir}


@given("a session is active with raw host observations and a note", target_fixture="running")
def a_session_with_raw_observations_and_note(
    loaded: PluginHandle, raw_task_suite: Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    project = FakeProject("readProject")
    install_host(monkeypatch, project=project, canvas=lambda: None)
    _start(loaded, DEMO_TASK_ID, raw_task_suite)
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    project.layersAdded.fire(["layer-1"])
    loaded.call("log_note", message="mid-take")
    return {"recorder": recorder, "output_dir": recorder.output_dir}


# --- Then: sessions ----------------------------------------------------------


@then("the session directory sits under the task's baselines folder")
def the_session_dir_is_under_baselines(started: dict, pilot_tasks: Path) -> None:
    expected = (pilot_tasks / "baselines").resolve()
    assert started["output_dir"].parent.parent == expected
    assert started["output_dir"].name.startswith("session-")


@then("the event log opens with a session_start event")
def the_log_opens_with_session_start(started: dict) -> None:
    first = read_events(started["output_dir"])[0]
    assert first["event"] == "session_start"
    assert first["task_id"] == started["recorder"].task_id


@then("the start event pins the task file and fixture SHA-256 values")
def the_start_event_pins_hashes(started: dict) -> None:
    first = read_events(started["output_dir"])[0]
    assert len(first["task_file_sha256"]) == 64
    assert len(first["fixture_sha256"]) == 64


@then("the UTC start time is recorded")
def the_utc_start_time_is_recorded(started: dict) -> None:
    opened = started["recorder"].started_at
    assert opened.tzinfo is not None
    assert opened.utcoffset().total_seconds() == 0


@then(parsers.parse('the event log contains a "{event}" event carrying that message'))
def the_log_contains_the_note(running: dict, event: str) -> None:
    notes = [
        entry
        for entry in read_events(running["output_dir"])
        if entry["event"] == event and entry.get("message") == "re-read the prompt"
    ]
    assert len(notes) == 1


@then("the reply reports that the session holds two events")
def the_reply_counts_events(reply: str) -> None:
    assert "2 events so far" in reply


@then("human-reference-record.json exists in the session directory")
def the_record_exists(running: dict) -> None:
    assert (running["output_dir"] / "human-reference-record.json").is_file()


@then("the record leaves study steps and tools pending review")
def the_record_leaves_metrics_pending_review(running: dict) -> None:
    record = read_record(running["output_dir"])
    assert record["record_version"] == 2
    assert record["session"]["steps"] is None
    assert record["session"]["tools"] is None
    assert record["session"]["metrics_status"] == "pending_review"
    assert record["study_metrics"]["status"] == "pending_review"
    assert record["study_metrics"]["pending_reasons"]


@then("the record retains raw observations separately from study metrics")
def the_record_retains_raw_observations_separately(running: dict) -> None:
    record = read_record(running["output_dir"])
    observations = record["observations"]
    assert observations["raw_event_count"] == 2
    assert observations["sources"] == ["host:project", "note"]
    assert record["study_metrics"]["processing_step_count"] is None
    assert record["study_metrics"]["processing_tools"] is None
    events = read_events(running["output_dir"])
    assert [e["event"] for e in events] == ["session_start", "layers_added", "note", "session_end"]
    assert events[1]["source"] == "host:project"
    assert "tool" not in events[1]
    assert events[2]["source"] == "note"
    assert "tool" not in events[2]


@then("the record reports missing processing history and pending manual review")
def the_record_reports_missing_processing_and_pending_review(running: dict) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["processing_hook_connected"] is False
    assert metrics["processing_step_count"] is None
    assert metrics["processing_tools"] is None
    assert metrics["manual_step_count"] is None
    assert metrics["pending_reasons"] == [
        "processing_history_unavailable",
        "manual_review_pending",
    ]


@then("the record hashes every output file the participant left behind")
def the_record_hashes_outputs(running: dict) -> None:
    """Every file the participant wrote is hashed; the log itself is not an output."""
    import hashlib

    record = read_record(running["output_dir"])
    on_disk = {
        path.name
        for path in running["output_dir"].iterdir()
        if path.is_file() and path.name not in {"events.jsonl", "human-reference-record.json"}
    }
    assert {output["path"] for output in record["outputs"]} == on_disk
    for output in record["outputs"]:
        path = running["output_dir"] / output["path"]
        assert output["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@then("the plugin reports no active session")
def the_plugin_has_no_active_session() -> None:
    assert plugin._ACTIVE["session"] is None


@then("the start is refused because a session is already running")
def the_start_is_refused(started: dict) -> None:
    assert started["reply"].startswith("session already active")


@then("the plugin explains that the session cannot be started")
def the_start_is_explained(started: dict) -> None:
    assert started["reply"].startswith("cannot start session")


@then("the event log records that the session was abandoned")
def the_log_records_abandonment(running: dict) -> None:
    events = [entry["event"] for entry in read_events(running["output_dir"])]
    assert "session_abandoned" in events


@then("a session-abandoned marker exists in the session directory")
def the_abandon_marker_exists(running: dict) -> None:
    import json

    marker = running["output_dir"] / "session-abandoned.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["record_written"] is False


@then("no human-reference-record.json is written")
def no_record_is_written(running: dict) -> None:
    assert not (running["output_dir"] / "human-reference-record.json").exists()


@then(parsers.parse('the task manifest\'s human_baseline status stays "{status}"'))
def the_manifest_status_is_unchanged(running: dict, status: str) -> None:
    import yaml

    manifest = running["recorder"].task_yaml
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert data["human_baseline"]["status"] == status


@then(parsers.parse('the plugin answers "{expected}"'))
def the_plugin_answers(reply: str, expected: str) -> None:
    assert reply == expected


@when(
    parsers.parse('I start two sessions for task "{task_id}" in the same second'),
    target_fixture="two_sessions",
)
def start_two_sessions_in_one_second(
    loaded: PluginHandle, pilot_tasks: Path, monkeypatch: pytest.MonkeyPatch, task_id: str
) -> list:
    from datetime import UTC, datetime

    from experiment_plugin import session as baseline

    fixed = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(baseline, "utc_now", lambda: fixed)
    first = baseline.start_session(task_id, pilot_tasks)
    second = baseline.start_session(task_id, pilot_tasks)
    return [first, second]


@then("each session has its own directory and its own event log")
def two_sessions_are_distinct(two_sessions: list) -> None:
    first, second = two_sessions
    assert first.output_dir != second.output_dir
    assert first.output_dir.name == "session-20261122T100000Z"
    assert second.output_dir.name == "session-20261122T100000Z-2"
    assert read_events(first.output_dir)
    assert read_events(second.output_dir)


# --- When/Then: the session panel --------------------------------------------


def _panel(loaded: PluginHandle, initial: dict | None = None):
    dialog = plugin.SessionPanelDialog()
    dialog.initial = initial or {}
    dialog.ctx = view_context(loaded)
    dialog.build()
    return dialog


@given("the panel is open", target_fixture="panel_state")
def the_panel_is_open(loaded: PluginHandle) -> dict:
    return {"dialog": _panel(loaded), "handle": loaded}


@when("I ask the plugin to show the session panel", target_fixture="reply")
def ask_for_the_panel(loaded: PluginHandle) -> str:
    return loaded.call("show_timer")


@then("the plugin explains that the panel needs a GUI host")
def panel_needs_gui(reply: str) -> None:
    assert "no ui capability" in reply


@when("I open the session panel with no session", target_fixture="panel_state")
def open_panel_without_session(loaded: PluginHandle, qt) -> dict:
    return {"dialog": _panel(loaded), "handle": loaded}


@when("I open the session panel", target_fixture="panel_state")
def open_panel(loaded: PluginHandle, qt, running: dict) -> dict:
    recorder = running["recorder"]
    initial = {"started_at": recorder.started_at.isoformat(), "task_id": recorder.task_id}
    return {"dialog": _panel(loaded, initial), "handle": loaded}


@then(parsers.parse('the panel has a "{first}" tab and a "{second}" tab'))
def panel_has_tabs(panel_state: dict, first: str, second: str) -> None:
    tabs = next(
        widget for widget in panel_state["dialog"]._parts.values() if hasattr(widget, "tabs")
    )
    assert [title for title, _ in tabs.tabs] == [first, second]


@then(parsers.parse('the panel offers the buttons "{expected}"'))
def panel_offers_buttons(panel_state: dict, expected: str) -> None:
    parts = panel_state["dialog"]._parts
    assert [
        parts[name].text() for name in ("start_button", "stop_button", "restart_button")
    ] == expected.split(", ")


@then("only the Start button is available")
def only_start_is_available(panel_state: dict) -> None:
    parts = panel_state["dialog"]._parts
    assert parts["start_button"].enabled is True
    assert parts["stop_button"].enabled is False
    assert parts["restart_button"].enabled is False


@then("the panel shows the session's task in its task field")
def panel_shows_task(panel_state: dict) -> None:
    assert panel_state["dialog"]._parts["task_edit"].text() == DEMO_TASK_ID


@then("the panel says the session is recording")
def panel_says_recording(panel_state: dict) -> None:
    assert "recording" in panel_state["dialog"]._parts["status_label"].text()


@then("the clock reads zero")
def clock_reads_zero(panel_state: dict) -> None:
    import re

    assert re.fullmatch(r"00:00:\d\d", panel_state["dialog"]._parts["elapsed_label"].text())


@when(
    parsers.parse('I start a session from the panel for task "{task_id}" as participant "{code}"'),
    target_fixture="panel_state",
)
def start_from_panel_with_participant(
    loaded: PluginHandle, qt, task_suite, task_id: str, code: str
) -> dict:
    dialog = _panel(loaded, {"task_id": task_id})
    dialog._parts["task_edit"].setText(task_id)
    dialog._parts["participant_edit"].setText(code)
    dialog._parts["start_button"].click()
    return {"dialog": dialog, "handle": loaded, "code": code}


@when(
    parsers.parse('I start a session from the panel for task "{task_id}"'),
    target_fixture="panel_state",
)
def start_from_panel(loaded: PluginHandle, qt, task_suite, task_id: str) -> dict:
    dialog = _panel(loaded, {"task_id": task_id})
    dialog._parts["task_edit"].setText(task_id)
    dialog._parts["start_button"].click()
    return {"dialog": dialog, "handle": loaded}


@then("the panel says the session started")
def panel_says_started(panel_state: dict) -> None:
    status = panel_state["dialog"]._parts["status_label"].text()
    assert f"session started for task {DEMO_TASK_ID}" in status


@then("the task field becomes read-only")
def task_field_read_only(panel_state: dict) -> None:
    assert panel_state["dialog"]._parts["task_edit"].enabled is False


@then("the Stop button becomes available")
def stop_button_available(panel_state: dict) -> None:
    assert panel_state["dialog"]._parts["stop_button"].enabled is True


@when("I stop the session from the panel", target_fixture="stopped")
def stop_from_panel(panel_state: dict) -> dict:
    panel_state["dialog"]._parts["stop_button"].click()
    return panel_state


@then("human-reference-record.json exists for the panel's session")
def panel_session_has_record() -> None:
    last = plugin._LAST["session"]
    assert last is not None
    assert (last.output_dir / "human-reference-record.json").is_file()


@then("the panel returns to its idle state")
def panel_is_idle(stopped: dict) -> None:
    parts = stopped["dialog"]._parts
    assert parts["start_button"].enabled is True
    assert parts["stop_button"].enabled is False


@when("I restart the session from the panel and confirm", target_fixture="restarted")
def restart_and_confirm(panel_state: dict) -> dict:
    previous = plugin._ACTIVE["session"]
    assert previous is not None
    FakeMessageBox._answer = FakeMessageBox.StandardButton.Yes
    panel_state["dialog"]._parts["restart_button"].click()
    return {
        **panel_state,
        "previous": previous,
        "previous_evidence": _evidence_snapshot(previous.output_dir),
    }


@then("the previous take is marked abandoned and has no record")
def previous_take_abandoned(restarted: dict) -> None:
    previous = restarted["previous"]
    assert (previous.output_dir / "session-abandoned.json").exists()
    assert not (previous.output_dir / "human-reference-record.json").exists()


@then("a new session is running for the same task and participant")
def new_session_matches(restarted: dict) -> None:
    previous = restarted["previous"]
    current = plugin._ACTIVE["session"]
    assert current is not None and current is not previous
    assert current.task_id == previous.task_id
    assert current.participant_code == previous.participant_code


@when("I restart the session from the panel and cancel", target_fixture="cancelled")
def restart_and_cancel(panel_state: dict) -> dict:
    previous = plugin._ACTIVE["session"]
    FakeMessageBox._answer = FakeMessageBox.StandardButton.No
    panel_state["dialog"]._parts["restart_button"].click()
    return {**panel_state, "previous": previous}


@then("the same session is still running")
def same_session_running(cancelled: dict) -> None:
    assert plugin._ACTIVE["session"] is cancelled["previous"]


@then("the panel says the restart was cancelled")
def panel_says_cancelled(cancelled: dict) -> None:
    assert "cancelled" in cancelled["dialog"]._parts["status_label"].text()


@when("the panel's clock ticks")
def clock_ticks(panel_state: dict) -> None:
    FakeTimer.instances[0].timeout.fire()


@then("the clock still shows a fixed elapsed time")
def clock_is_fixed(stopped: dict) -> None:
    import re

    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", stopped["dialog"]._parts["elapsed_label"].text())


@then("the log view contains the session_start event")
def log_view_has_start(panel_state: dict) -> None:
    assert "session_start" in panel_state["dialog"]._parts["log_edit"].toPlainText()


@then("the log header names the task")
def log_header_names_task(panel_state: dict) -> None:
    assert DEMO_TASK_ID in panel_state["dialog"]._parts["log_header"].text()


@when("I export the log to a file", target_fixture="exported")
def export_log(panel_state: dict, tmp_path) -> dict:
    target = tmp_path / "exported-log.txt"
    FakeFileDialog._next_path = str(target)
    panel_state["dialog"]._parts["export_button"].click()
    return {**panel_state, "target": target}


@then("the exported file is a human-readable session log containing session_start")
def export_is_readable(exported: dict) -> None:
    content = exported["target"].read_text(encoding="utf-8")
    assert content.splitlines()[0].startswith("human-baseline session log")
    assert "session_start" in content
    assert "exported" in exported["dialog"]._parts["status_label"].text()


@when("I cancel the export", target_fixture="exported")
def cancel_export(panel_state: dict) -> dict:
    FakeFileDialog._next_path = ""
    panel_state["dialog"]._parts["export_button"].click()
    return panel_state


@then("no file is written and the panel says the export was cancelled")
def export_cancelled(exported: dict) -> None:
    assert "cancelled" in exported["dialog"]._parts["status_label"].text()


@when("I ask the panel to export", target_fixture="exported")
def ask_panel_to_export(panel_state: dict) -> dict:
    panel_state["dialog"]._parts["export_button"].click()
    return panel_state


@then("the panel says there is no session to export")
def no_session_to_export(exported: dict) -> None:
    assert "no session to export" in exported["dialog"]._parts["status_label"].text()


@when("I export the log to a location that cannot be written", target_fixture="exported")
def export_to_bad_location(panel_state: dict) -> dict:
    FakeFileDialog._next_path = "/no-such-directory-xyz/exported-log.txt"
    panel_state["dialog"]._parts["export_button"].click()
    return panel_state


@then("the panel reports that the export failed")
def export_failed(exported: dict) -> None:
    assert "export failed:" in exported["dialog"]._parts["status_label"].text()


@when("I start a session from a panel on a host without actions", target_fixture="panel_state")
def start_without_actions(loaded: PluginHandle, qt) -> dict:
    class _NoActions:
        def has(self, name: str) -> bool:
            return name != "actions"

        @property
        def actions(self):
            raise AssertionError("actions must not be read without the capability")

    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": DEMO_TASK_ID}
    dialog.ctx = _NoActions()
    dialog.build()
    dialog._parts["start_button"].click()
    return {"dialog": dialog}


@then("the panel says the host has no actions capability")
def no_actions_capability(panel_state: dict) -> None:
    assert "no actions capability" in panel_state["dialog"]._parts["status_label"].text()


@when(
    "I start a session from a panel whose action dispatch is unavailable",
    target_fixture="panel_state",
)
def start_with_broken_dispatch(loaded: PluginHandle, qt) -> dict:
    class _HasRaises:
        def has(self, name: str) -> bool:
            raise RuntimeError("boom")

    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": DEMO_TASK_ID}
    dialog.ctx = _HasRaises()
    dialog.build()
    dialog._parts["start_button"].click()
    return {"dialog": dialog}


@then("the panel reports that the actions are unavailable")
def actions_unavailable(panel_state: dict) -> None:
    assert "actions unavailable: boom" in panel_state["dialog"]._parts["status_label"].text()


@when("I start a session from a panel whose start action raises", target_fixture="panel_state")
def start_with_raising_action(loaded: PluginHandle, qt) -> dict:
    class _BrokenActions:
        def start_session(self, **kwargs):
            raise RuntimeError("boom")

    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": DEMO_TASK_ID}
    dialog.ctx = view_context(loaded, actions=_BrokenActions())
    dialog.build()
    dialog._parts["start_button"].click()
    return {"dialog": dialog}


@then("the panel reports that the start failed")
def start_failed(panel_state: dict) -> None:
    assert "start_session failed: boom" in panel_state["dialog"]._parts["status_label"].text()


@when(
    parsers.parse('I ask the panel to dispatch the undeclared action "{action_id}"'),
    target_fixture="panel_reply",
)
def dispatch_undeclared(loaded: PluginHandle, qt, action_id: str) -> str:
    dialog = _panel(loaded)
    return dialog._call_action(action_id)


@then(parsers.parse('the panel answers "{expected}"'))
def panel_answers(panel_reply: str, expected: str) -> None:
    assert panel_reply == expected


# --- the QGIS host ----------------------------------------------------------

START = 'I start a session for task "{task_id}"'


@given("a QGIS host with a project open", target_fixture="host")
def host_with_project(monkeypatch: pytest.MonkeyPatch) -> dict:
    project = FakeProject("readProject")
    install_host(monkeypatch, project=project)
    return {"project": project}


@given(
    parsers.parse('a QGIS host with a project that only offers the "{signal}" signal'),
    target_fixture="host",
)
def host_with_qgis3_project(monkeypatch: pytest.MonkeyPatch, signal: str) -> dict:
    project = FakeProject(signal)
    install_host(monkeypatch, project=project)
    return {"project": project}


@given("a QGIS host with a project that offers no read signal", target_fixture="host")
def host_without_read_signal(monkeypatch: pytest.MonkeyPatch) -> dict:
    project = FakeProject(None)
    install_host(monkeypatch, project=project)
    return {"project": project}


@given("a QGIS host with a map canvas and a running session", target_fixture="host")
def host_with_canvas_and_session(
    monkeypatch: pytest.MonkeyPatch, loaded: PluginHandle, task_suite: Path
) -> dict:
    """We have to start the session *after* the host is faked, so the canvas
    hooks are wired to this canvas rather than to no host at all."""
    canvas = FakeCanvas()
    install_host(monkeypatch, project=FakeProject("readProject"), canvas=lambda: canvas)
    loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    return {"canvas": canvas, "running": {"recorder": recorder, "output_dir": recorder.output_dir}}


@given("a QGIS host with a project and a map canvas open", target_fixture="host")
def host_with_project_and_canvas(monkeypatch: pytest.MonkeyPatch) -> dict:
    project = FakeProject("readProject")
    canvas = FakeCanvas()
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    return {"project": project, "canvas": canvas}


@given("a QGIS host with a project, a map canvas and the session panel", target_fixture="host")
def host_with_panel(qt, monkeypatch: pytest.MonkeyPatch) -> dict:
    return host_with_project_and_canvas(monkeypatch)


@given("a QGIS host with a removable map canvas", target_fixture="host")
def host_with_removable_canvas(monkeypatch: pytest.MonkeyPatch) -> dict:
    class RemovableCanvas(FakeCanvas):
        deleted = False

        def __getattribute__(self, name):
            if name in ("extentsChanged", "scaleChanged") and self.deleted:
                raise RuntimeError("wrapped canvas has been deleted")
            return super().__getattribute__(name)

    project = FakeProject("readProject")
    canvas = RemovableCanvas()
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    return {"project": project, "canvas": canvas}


@given("another component listens to project and canvas changes")
def other_component_listens(host: dict) -> None:
    received = []

    def layer_listener(_layers) -> None:
        received.append("layer")

    def scale_listener(_scale) -> None:
        received.append("scale")

    host["project"].layersAdded.connect(layer_listener)
    host["canvas"].scaleChanged.connect(scale_listener)
    host["other_received"] = received
    host["other_listeners"] = (layer_listener, scale_listener)


@given("a canvas signal refuses to disconnect")
def canvas_refuses_disconnect(host: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_to_disconnect(_slot) -> None:
        raise RuntimeError("canvas scale disconnect refused")

    monkeypatch.setattr(host["canvas"].scaleChanged, "disconnect", fail_to_disconnect)


@given("a QGIS host whose project hooks fail partway through wiring", target_fixture="host")
def host_with_partly_broken_project(monkeypatch: pytest.MonkeyPatch) -> dict:
    project = FakeProject("readProject")
    canvas = FakeCanvas()

    def fail_to_connect(_slot) -> None:
        raise RuntimeError("layer removal signal refused")

    monkeypatch.setattr(project.layersWillBeRemoved, "connect", fail_to_connect)
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    return {"project": project, "canvas": canvas}


@given("a QGIS host with a failing project hook and the session panel", target_fixture="host")
def host_with_partial_project_and_panel(qt, monkeypatch: pytest.MonkeyPatch) -> dict:
    return host_with_partly_broken_project(monkeypatch)


@given("a QGIS host whose canvas hooks fail after connecting", target_fixture="host")
def host_with_partly_broken_canvas(monkeypatch: pytest.MonkeyPatch) -> dict:
    project = FakeProject("readProject")
    canvas = FakeCanvas()
    connect = canvas.scaleChanged.connect

    def fail_after_connect(slot) -> None:
        connect(slot)
        raise RuntimeError("canvas scale signal refused")

    monkeypatch.setattr(canvas.scaleChanged, "connect", fail_after_connect)
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    return {"project": project, "canvas": canvas}


@given("a QGIS host whose map canvas cannot be wired", target_fixture="host")
def host_with_broken_canvas(monkeypatch: pytest.MonkeyPatch) -> dict:
    install_host(
        monkeypatch,
        project=FakeProject("readProject"),
        iface_raises=RuntimeError("iface exploded"),
    )
    return {}


@given("no QGIS host on this machine", target_fixture="host")
def no_host(monkeypatch: pytest.MonkeyPatch) -> dict:
    remove_host(monkeypatch)
    return {}


@given("a session is active", target_fixture="running")
def session_active(loaded: PluginHandle, task_suite: Path) -> dict:
    reply = loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None, reply
    return {"recorder": recorder, "output_dir": recorder.output_dir, "reply": reply}


@given("the abandonment marker cannot be written")
def abandonment_marker_unwritable(monkeypatch: pytest.MonkeyPatch) -> None:
    write_text = Path.write_text

    def fail_marker(path: Path, *args, **kwargs):
        if path.name == "session-abandoned.json":
            raise OSError("abandonment marker is unwritable")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_marker)


@when("I try to abandon the session", target_fixture="abandon_error")
def try_to_abandon_session(loaded: PluginHandle) -> Exception | None:
    try:
        loaded.call("abandon_session")
    except OSError as exc:
        return exc
    return None


@then("the abandonment failure is reported")
def abandonment_failure_is_reported(abandon_error: Exception | None, running: dict) -> None:
    assert isinstance(abandon_error, OSError)
    assert "abandonment marker is unwritable" in str(abandon_error)
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "session_abandoned",
    ]


@given("the task fixture is unavailable")
def task_fixture_unavailable(task_suite: Path) -> None:
    (task_suite / "fixture.geojson").unlink()


@when("I try to end the session", target_fixture="end_error")
def try_to_end_session(loaded: PluginHandle) -> Exception | None:
    try:
        loaded.call("end_session")
    except OSError as exc:
        return exc
    return None


@then("the end failure is reported")
def end_failure_is_reported(end_error: Exception | None) -> None:
    assert isinstance(end_error, FileNotFoundError)
    assert "fixture.geojson" in str(end_error)


@when("I end the session despite the disconnection failure", target_fixture="disconnect_error")
def end_with_disconnect_failure(loaded: PluginHandle) -> Exception | None:
    try:
        loaded.call("end_session")
    except Exception as exc:
        return exc
    return None


def _exception_messages(error: BaseException) -> list[str]:
    if isinstance(error, BaseExceptionGroup):
        return [message for child in error.exceptions for message in _exception_messages(child)]
    return [str(error)]


@then("the disconnection failure is reported")
def disconnect_failure_is_reported(disconnect_error: Exception | None) -> None:
    assert isinstance(disconnect_error, ExceptionGroup)
    assert "canvas scale disconnect refused" in _exception_messages(disconnect_error)


@when("I try to unload the plugin", target_fixture="unload_error")
def try_to_unload(loaded: PluginHandle) -> Exception | None:
    try:
        loaded.unload()
    except Exception as exc:
        return exc
    return None


@then("the unload reports the abandonment failure")
def unload_reports_abandonment_failure(unload_error: Exception | None, running: dict) -> None:
    assert isinstance(unload_error, ExceptionGroup)
    assert "abandonment marker is unwritable" in _exception_messages(unload_error)
    assert running["recorder"].status == "incomplete"


@then("the unload reports both failures")
def unload_reports_both_failures(unload_error: Exception | None) -> None:
    assert isinstance(unload_error, ExceptionGroup)
    messages = _exception_messages(unload_error)
    assert "abandonment marker is unwritable" in messages
    assert "canvas scale disconnect refused" in messages


@then("the remaining host hooks were disconnected")
def remaining_hooks_were_disconnected(host: dict) -> None:
    project, canvas = host["project"], host["canvas"]
    assert len(canvas.scaleChanged.slots) == 1
    assert all(
        not signal.slots
        for signal in (
            project.layersAdded,
            project.layersWillBeRemoved,
            project.crsChanged,
            project.readProject,
            canvas.extentsChanged,
        )
    )


@when("two layers are added, one is removed, the project CRS changes and the project is read")
def drive_project_signals(host: dict) -> None:
    project = host["project"]
    project.layersAdded.fire(["a", "b"])
    project.layersWillBeRemoved.fire(["a"])
    project.crsChanged.fire()
    project.readProject.fire()


@when("the canvas extent changes and the canvas scale changes")
def drive_canvas_signals(host: dict) -> None:
    canvas = host["canvas"]
    canvas.extentsChanged.fire()
    canvas.scaleChanged.fire(50000.0)


@when("the map canvas is destroyed")
def destroy_map_canvas(host: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    canvas = host["canvas"]

    def stale_signal_disconnect(_slot) -> None:
        raise AssertionError("a destroyed canvas signal cannot safely be accessed")

    for signal in (canvas.extentsChanged, canvas.scaleChanged):
        signal.slots.clear()  # Qt disconnects a destroyed object's signals.
        monkeypatch.setattr(signal, "disconnect", stale_signal_disconnect)
    canvas.deleted = True


@when("the project CRS changes")
def drive_crs_change(host: dict) -> None:
    host["project"].crsChanged.fire()


@then("the surviving project hooks are disconnected")
def surviving_project_hooks_are_disconnected(host: dict) -> None:
    project = host["project"]
    assert all(
        not signal.slots
        for signal in (
            project.layersAdded,
            project.layersWillBeRemoved,
            project.crsChanged,
            project.readProject,
        )
    )


@when("every project and canvas signal fires")
def drive_every_host_signal(host: dict) -> None:
    project, canvas = host["project"], host["canvas"]
    project.layersAdded.fire(["a", "b"])
    project.layersWillBeRemoved.fire(["a"])
    project.crsChanged.fire()
    project.readProject.fire(object())
    canvas.extentsChanged.fire()
    canvas.scaleChanged.fire(50000.0)


@when("project and canvas changes are queued", target_fixture="queued_changes")
def queue_host_changes(host: dict) -> tuple:
    return (
        host["project"].layersAdded.queue(["a"]),
        host["canvas"].scaleChanged.queue(50000.0),
    )


@when("the queued changes are delivered")
def deliver_queued_changes(queued_changes: tuple) -> None:
    for deliver in queued_changes:
        deliver()


@when("the project is read using its legacy signal")
def drive_legacy_project_read(host: dict) -> None:
    host["project"].projectRead.fire()


@when("a layer is added and the project CRS changes")
def drive_partial_project_signals(host: dict) -> None:
    host["project"].layersAdded.fire(["a"])
    host["project"].crsChanged.fire()


@when("a layer is added and the canvas scale changes")
def drive_project_and_canvas_after_failure(host: dict) -> None:
    host["project"].layersAdded.fire(["a"])
    host["canvas"].scaleChanged.fire(50000.0)


@when(parsers.parse("the project reports {count:d} CRS changes"))
def flood_project_crs_changes(host: dict, count: int) -> None:
    for _ in range(count):
        host["project"].crsChanged.fire()


@then("the event log records two layers added")
def log_records_layers_added(running: dict) -> None:
    events = [e for e in read_events(running["output_dir"]) if e["event"] == "layers_added"]
    assert events[-1]["count"] == 2


@then("the event log records one layer removed")
def log_records_layers_removed(running: dict) -> None:
    events = [e for e in read_events(running["output_dir"]) if e["event"] == "layers_removed"]
    assert events[-1]["count"] == 1


@then("the event log records the project CRS")
def log_records_crs(running: dict) -> None:
    events = [e for e in read_events(running["output_dir"]) if e["event"] == "crs_changed"]
    assert events[-1]["crs"] == "EPSG:2180"


@then("the event log records the project file path")
def log_records_project_path(running: dict) -> None:
    events = [e for e in read_events(running["output_dir"]) if e["event"] == "project_read"]
    assert len(events) == 1
    assert events[0]["path"] == "/tmp/fake-project.qgs"


@then("the project observations keep their source and order")
def project_observations_keep_source_and_order(running: dict) -> None:
    events = read_events(running["output_dir"])
    assert [event["event"] for event in events] == [
        "session_start",
        "layers_added",
        "layers_removed",
        "crs_changed",
        "project_read",
    ]
    assert all(event["source"] == "host:project" for event in events[1:])
    assert all("tool" not in event for event in events[1:])


@then("the legacy project-read listener is disconnected")
def legacy_project_read_disconnected(host: dict, running: dict) -> None:
    assert not host["project"].projectRead.slots
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "project_read",
        "session_end",
    ]


@then("the start message reports the missing project read hook")
def start_message_reports_missing_hook(running: dict) -> None:
    assert "host hooks: project (partial)" in running["reply"]
    assert "host hook failed: project_read: no project-read signal found" in running["reply"]


@then("the event log records both project changes")
def log_records_partial_project_changes(running: dict) -> None:
    events = read_events(running["output_dir"])
    observations = [
        {key: value for key, value in event.items() if key != "ts"} for event in events[1:]
    ]
    assert observations == [
        {"event": "layers_added", "source": "host:project", "count": 1},
        {"event": "crs_changed", "source": "host:project", "crs": "EPSG:2180"},
    ]


@then("the start message reports the project hook failure")
def start_message_reports_project_failure(running: dict) -> None:
    assert "host hooks: canvas" in running["reply"]
    assert "host hook failed: project: layer removal signal refused" in running["reply"]


@then("the event log records the connected project and canvas changes")
def log_records_changes_after_project_failure(running: dict) -> None:
    events = read_events(running["output_dir"])
    observations = [
        {key: value for key, value in event.items() if key != "ts"} for event in events[1:]
    ]
    assert observations == [
        {"event": "layers_added", "source": "host:project", "count": 1},
        {"event": "canvas_scale", "source": "host:canvas", "scale": 50000.0},
    ]


@then("the start message reports the partial canvas hook failure")
def start_message_reports_partial_canvas_failure(running: dict) -> None:
    assert "host hooks: project" in running["reply"]
    assert "host hook failed: canvas: canvas scale signal refused" in running["reply"]


@then("the completed event log keeps only the earlier project and canvas changes")
def completed_log_keeps_connected_changes(running: dict) -> None:
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "layers_added",
        "canvas_scale",
        "session_end",
    ]


@then("the abandoned event log keeps only the earlier project and canvas changes")
def abandoned_log_keeps_connected_changes(running: dict) -> None:
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "layers_added",
        "canvas_scale",
        "session_abandoned",
    ]
    assert not (running["output_dir"] / "human-reference-record.json").exists()


@then("all host hooks are disconnected")
def all_host_hooks_disconnected(host: dict) -> None:
    project, canvas = host["project"], host["canvas"]
    signals = (
        project.layersAdded,
        project.layersWillBeRemoved,
        project.crsChanged,
        project.readProject,
        canvas.extentsChanged,
        canvas.scaleChanged,
    )
    assert all(not signal.slots for signal in signals)


@then("the panel reports the project hook failure")
def panel_reports_project_hook_failure(panel_state: dict) -> None:
    status = panel_state["dialog"]._parts["status_label"].text()
    assert "host hook failed: project: layer removal signal refused" in status


@then("the panel reports the disconnection failure")
def panel_reports_disconnection_failure(stopped: dict) -> None:
    status = stopped["dialog"]._parts["status_label"].text()
    assert "end_session failed: " in status
    assert "canvas scale disconnect refused" in status


@then("the panel's session records the connected host changes")
def panel_session_records_host_changes() -> None:
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    assert [event["event"] for event in read_events(recorder.output_dir)] == [
        "session_start",
        "layers_added",
        "canvas_scale",
    ]


@then("the other component still receives both changes")
def other_component_receives_changes(host: dict) -> None:
    assert host["other_received"] == ["layer", "scale"]


@then("no session callbacks remain connected")
def no_session_callbacks_remain(host: dict) -> None:
    project, canvas = host["project"], host["canvas"]
    layer_listener, scale_listener = host["other_listeners"]
    assert project.layersAdded.slots == [layer_listener]
    assert canvas.scaleChanged.slots == [scale_listener]
    assert all(
        not signal.slots
        for signal in (
            project.layersWillBeRemoved,
            project.crsChanged,
            project.readProject,
            canvas.extentsChanged,
        )
    )


@then("the event log records the extent and the scale")
def log_records_extent_and_scale(host: dict) -> None:
    events = read_events(host["running"]["output_dir"])
    observations = [
        {key: value for key, value in event.items() if key != "ts"}
        for event in events
        if event["event"] in {"canvas_extent", "canvas_scale"}
    ]
    assert observations == [
        {
            "event": "canvas_extent",
            "source": "host:canvas",
            "extent": {"xmin": 0.0, "ymin": 1.0, "xmax": 100.0, "ymax": 51.0},
        },
        {"event": "canvas_scale", "source": "host:canvas", "scale": 50000.0},
    ]


@then("the completed event log keeps the host observations in order")
def completed_log_keeps_host_observations(running: dict) -> None:
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "layers_added",
        "layers_removed",
        "crs_changed",
        "project_read",
        "canvas_extent",
        "canvas_scale",
        "session_end",
    ]


@then("the finished event log contains only the session markers")
def finished_log_contains_only_markers(running: dict) -> None:
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "session_end",
    ]


@then("the abandoned event log contains only the session markers")
def abandoned_log_contains_only_markers(running: dict) -> None:
    assert [event["event"] for event in read_events(running["output_dir"])] == [
        "session_start",
        "session_abandoned",
    ]


def _evidence_snapshot(output_dir: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in output_dir.iterdir() if path.is_file()}


@when("I capture the terminal evidence", target_fixture="terminal_evidence")
def capture_terminal_evidence(running: dict) -> dict[str, bytes]:
    return _evidence_snapshot(running["output_dir"])


@then("the terminal evidence remains unchanged")
def terminal_evidence_is_unchanged(running: dict, terminal_evidence: dict[str, bytes]) -> None:
    assert _evidence_snapshot(running["output_dir"]) == terminal_evidence


@when("I start a new session", target_fixture="new_take")
def start_new_take(loaded: PluginHandle, task_suite: Path) -> Path:
    reply = _start(loaded, DEMO_TASK_ID, task_suite)
    assert reply.startswith("session started for task"), reply
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    return recorder.output_dir


@then("the new session alone records every host change")
def new_take_alone_records_changes(host: dict, running: dict, new_take: Path) -> None:
    assert new_take != running["output_dir"]
    assert [event["event"] for event in read_events(new_take)] == [
        "session_start",
        "layers_added",
        "layers_removed",
        "crs_changed",
        "project_read",
        "canvas_extent",
        "canvas_scale",
    ]
    project, canvas = host["project"], host["canvas"]
    signals = (
        project.layersAdded,
        project.layersWillBeRemoved,
        project.crsChanged,
        project.readProject,
        canvas.extentsChanged,
        canvas.scaleChanged,
    )
    assert all(len(signal.slots) == 1 for signal in signals)


@when("I capture the panel's terminal evidence", target_fixture="panel_evidence")
def capture_panel_evidence(stopped: dict) -> tuple[Path, dict[str, bytes]]:
    last = plugin._LAST["session"]
    assert last is not None, stopped["dialog"]._parts["status_label"].text()
    return last.output_dir, _evidence_snapshot(last.output_dir)


@then("the panel's terminal evidence remains unchanged")
def panel_evidence_is_unchanged(panel_evidence: tuple[Path, dict[str, bytes]]) -> None:
    output_dir, snapshot = panel_evidence
    assert _evidence_snapshot(output_dir) == snapshot
    assert [event["event"] for event in read_events(output_dir)] == [
        "session_start",
        "session_end",
    ]


@then("the previous take's evidence remains unchanged")
def previous_evidence_is_unchanged(restarted: dict) -> None:
    assert _evidence_snapshot(restarted["previous"].output_dir) == restarted["previous_evidence"]


@then("the original session records the host changes")
def original_session_records_changes(cancelled: dict) -> None:
    assert [event["event"] for event in read_events(cancelled["previous"].output_dir)] == [
        "session_start",
        "layers_added",
        "canvas_scale",
    ]


@then("the panel reports the abandonment failure")
def panel_reports_abandon_failure(restarted: dict) -> None:
    status = restarted["dialog"]._parts["status_label"].text()
    assert "abandon_session failed: abandonment marker is unwritable" in status


@then("the incomplete take has no record and no new session was started")
def incomplete_take_is_not_promoted(restarted: dict) -> None:
    previous = restarted["previous"]
    assert previous.status == "incomplete"
    assert not (previous.output_dir / "human-reference-record.json").exists()
    assert list(previous.output_dir.parent.iterdir()) == [previous.output_dir]
    assert plugin._ACTIVE["session"] is None


@then("the restarted session records the host changes")
def restarted_session_records_changes(restarted: dict) -> None:
    current = plugin._ACTIVE["session"]
    assert current is not None and current is not restarted["previous"]
    assert [event["event"] for event in read_events(current.output_dir)] == [
        "session_start",
        "layers_added",
        "canvas_scale",
    ]


@when("the plugin is unloaded and reloaded", target_fixture="reloaded")
def unload_and_reload(loaded: PluginHandle, running: dict) -> dict:
    loaded.unload()
    snapshot = _evidence_snapshot(running["output_dir"])
    replacement = PluginHandle()
    try:
        yield {"handle": replacement, "snapshot": snapshot}
    finally:
        replacement.unload()


@when("I start another session and trigger project and canvas changes")
def start_another_and_trigger_changes(reloaded: dict, host: dict, task_suite: Path) -> None:
    reply = _start(reloaded["handle"], DEMO_TASK_ID, task_suite)
    assert reply.startswith("session started for task"), reply
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    reloaded["output_dir"] = recorder.output_dir
    host["project"].layersAdded.fire(["a"])
    host["canvas"].scaleChanged.fire(50000.0)


@then("the unloaded take is marked abandoned without a record")
def unloaded_take_is_abandoned(running: dict) -> None:
    output_dir = running["output_dir"]
    marker = json.loads((output_dir / "session-abandoned.json").read_text(encoding="utf-8"))
    assert marker["reason"] == "plugin unloaded"
    assert marker["record_written"] is False
    assert not (output_dir / "human-reference-record.json").exists()
    assert [event["event"] for event in read_events(output_dir)] == [
        "session_start",
        "session_abandoned",
    ]


@then("the unloaded take's evidence remains unchanged")
def unloaded_evidence_is_unchanged(running: dict, reloaded: dict) -> None:
    assert _evidence_snapshot(running["output_dir"]) == reloaded["snapshot"]


@then("only the new session records those host changes")
def only_new_session_records_changes(running: dict, reloaded: dict) -> None:
    assert reloaded["output_dir"] != running["output_dir"]
    assert [event["event"] for event in read_events(reloaded["output_dir"])] == [
        "session_start",
        "layers_added",
        "canvas_scale",
    ]


@then(parsers.parse("the event log contains {count:d} entries"))
def event_log_contains_entries(running: dict, count: int) -> None:
    events = read_events(running["output_dir"])
    assert len(events) == count
    assert events[0]["event"] == "session_start"
    assert all(event["event"] == "crs_changed" for event in events[1:])


@then("the start message says no host hooks were connected")
def start_message_has_no_hooks(started: dict) -> None:
    assert "host hooks: none" in started["reply"]


@then("the start message lists the wired host hooks")
def start_message_lists_hooks(started: dict) -> None:
    assert "host hooks: " in started["reply"]
    assert "project" in started["reply"] and "canvas" in started["reply"]


@then("the start message offers no hook failures")
def start_message_has_no_failures(started: dict) -> None:
    assert "host hook failed" not in started["reply"]


@then("the start message reports the canvas hook failure")
def start_message_reports_canvas_failure(started: dict) -> None:
    assert "host hooks: project" in started["reply"]
    assert "host hook failed: canvas: iface exploded" in started["reply"]


@given("a QGIS host with project, canvas, and processing history open", target_fixture="host")
def host_with_project_canvas_and_processing(monkeypatch: pytest.MonkeyPatch) -> dict:
    project = FakeProject("readProject")
    canvas = FakeCanvas()
    history = FakeHistoryRegistry()
    install_host(
        monkeypatch,
        project=project,
        canvas=lambda: canvas,
        history_registry=history,
    )
    return {"project": project, "canvas": canvas, "history": history}


@given("a QGIS host whose processing history cannot be wired", target_fixture="host")
def host_with_broken_processing(monkeypatch: pytest.MonkeyPatch) -> dict:
    install_host(
        monkeypatch,
        project=FakeProject("readProject"),
        canvas=FakeCanvas,
        history_raises=RuntimeError("history registry exploded"),
    )
    return {}


@when("a layer is added, three processing algorithms run, and a note is logged")
def layer_three_algs_and_note(host: dict, loaded: PluginHandle) -> None:
    host["project"].layersAdded.fire(["layer-1"])
    host["history"].add_entry(
        "processing", {"algorithm_id": "native:buffer", "parameters": {"DISTANCE": 10}}
    )
    host["history"].add_entry(
        "processing", {"algorithm_id": "native:buffer", "parameters": {"DISTANCE": 20}}
    )
    host["history"].add_entry(
        "processing", {"algorithm_id": "native:clip", "parameters": {"OVERLAY": "mask"}}
    )
    loaded.call("log_note", message="checked parameters")


@when("a non-processing history entry and a malformed processing entry arrive")
def non_processing_and_malformed_entries(host: dict) -> None:
    host["history"].add_entry("dbquery", {"query": "SELECT 1"})
    host["history"].add_entry("processing", {"parameters": {"DISTANCE": 10}})


@when(parsers.parse('the processing algorithm "{algorithm_id}" executes'))
def processing_algorithm_executes(host: dict, algorithm_id: str) -> None:
    host["history"].add_entry(
        "processing", {"algorithm_id": algorithm_id, "parameters": {"INPUT": "poland"}}
    )


@then("the record preserves the observed processing executions and their algorithm ids")
def record_preserves_observed_processing(running: dict) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["processing_hook_connected"] is True
    assert metrics["processing_step_count"] == 3
    assert metrics["processing_tools"] == ["native:buffer", "native:clip"]
    assert [item["algorithm_id"] for item in metrics["processing_executions"]] == [
        "native:buffer",
        "native:buffer",
        "native:clip",
    ]
    assert metrics["manual_step_count"] is None
    assert metrics["pending_reasons"] == ["manual_review_pending"]
    events = [e for e in read_events(running["output_dir"]) if e["event"] == "processing_algorithm"]
    assert [e["algorithm_id"] for e in events] == ["native:buffer", "native:buffer", "native:clip"]
    assert all(e["source"] == "host:processing" for e in events)


@then("the record excludes raw host observations and notes from processing metrics")
def record_excludes_raw_from_processing(running: dict) -> None:
    record = read_record(running["output_dir"])
    assert record["observations"]["raw_event_count"] == 2
    assert record["observations"]["sources"] == ["host:project", "note"]
    assert "processing" in record["observations"]["hooks_connected"]
    for bad in ("host:project", "host:canvas", "note"):
        assert bad not in record["study_metrics"]["processing_tools"]


@then("the record notes zero observed processing executions while manual review is pending")
def record_notes_zero_processing_pending_review(running: dict) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["processing_hook_connected"] is True
    assert metrics["processing_step_count"] == 0
    assert metrics["processing_tools"] == []
    assert metrics["manual_step_count"] is None
    assert metrics["pending_reasons"] == ["manual_review_pending"]


@then("the record flags incomplete processing history without inventing an algorithm id")
def record_flags_incomplete_processing(running: dict) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["processing_step_count"] == 0
    assert metrics["processing_tools"] == []
    assert metrics["pending_reasons"] == ["processing_history_incomplete"]
    events = read_events(running["output_dir"])
    unparsed = [e for e in events if e["event"] == "processing_history_unparsed"]
    assert len(unparsed) == 1
    assert not [e for e in events if e["event"] == "processing_algorithm"]


@then("the start message reports the processing hook failure")
def start_message_reports_processing_failure(started: dict) -> None:
    assert "host hooks: project, canvas" in started["reply"]
    assert "host hook failed: processing: history registry exploded" in started["reply"]


@then(parsers.parse('the record preserves one observed processing execution for "{algorithm_id}"'))
def record_preserves_one_processing_execution(running: dict, algorithm_id: str) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["processing_step_count"] == 1
    assert metrics["processing_tools"] == [algorithm_id]
    assert record["session"]["steps"] is None
    assert record["session"]["tools"] is None


@when(
    parsers.parse('I log the manual action group "{action_group}"'),
    target_fixture="reply",
)
def log_manual_action_group(loaded: PluginHandle, action_group: str) -> str:
    return loaded.call("log_manual_action", action_group=action_group)


@when(
    parsers.parse('I log the manual action group "{action_group}" using tool "{tool}"'),
    target_fixture="reply",
)
def log_manual_action_group_with_tool(loaded: PluginHandle, action_group: str, tool: str) -> str:
    return loaded.call("log_manual_action", action_group=action_group, tool=tool)


@then("the plugin explains that a manual action group description is required")
def manual_action_group_requires_description(reply: str, running: dict) -> None:
    assert "required" in reply.lower()
    assert [e["event"] for e in read_events(running["output_dir"])] == ["session_start"]


@then("the record retains the manual action group without attributing a tool")
def record_retains_manual_group_without_tool(running: dict) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["manual_step_count"] is None
    assert metrics["pending_reasons"] == ["manual_review_pending"]
    assert len(metrics["manual_action_groups"]) == 1
    assert metrics["manual_action_groups"][0]["action_group"] == "styled Jenks classes"
    assert metrics["manual_action_groups"][0]["tool"] is None
    events = [e for e in read_events(running["output_dir"]) if e["event"] == "manual_action_group"]
    assert len(events) == 1
    assert events[0]["source"] == "manual"
    assert "tool" not in events[0]


@then(
    parsers.parse(
        "the record verifies {expected_steps:d} study steps and the observed processing tools"
    )
)
def record_verifies_steps_and_processing_tools(running: dict, expected_steps: int) -> None:
    record = read_record(running["output_dir"])
    assert record["session"]["steps"] == expected_steps
    assert record["session"]["tools"] == ["native:buffer", "native:clip"]
    assert record["session"]["metrics_status"] == "reviewed"
    metrics = record["study_metrics"]
    assert metrics["status"] == "reviewed"
    assert metrics["pending_reasons"] == []
    assert metrics["processing_step_count"] == 3
    assert metrics["manual_step_count"] == 1
    assert metrics["manual_review_completed"] is True
    assert record["observations"]["raw_event_count"] == 2
    assert record["observations"]["sources"] == ["host:project", "note"]


@then("the end summary reports reviewed steps and tools without raw sources")
def end_summary_reports_reviewed_metrics(reply: str) -> None:
    assert "steps: 4" in reply
    assert "native:buffer, native:clip" in reply
    assert "(reviewed)" in reply
    assert "host:project" not in reply
    assert "note" not in reply.splitlines()[1]


@then(
    parsers.parse(
        "the record verifies {expected_steps:d} study steps and an explicitly empty tools list"
    )
)
def record_verifies_steps_and_empty_tools(running: dict, expected_steps: int) -> None:
    record = read_record(running["output_dir"])
    assert record["session"]["steps"] == expected_steps
    assert record["session"]["tools"] == []
    assert record["session"]["metrics_status"] == "reviewed"
    assert record["study_metrics"]["status"] == "reviewed"
    assert record["study_metrics"]["processing_step_count"] == 0
    assert record["study_metrics"]["manual_step_count"] == expected_steps


@then("the record reports missing processing history while retaining the manual action group")
def record_reports_missing_processing_with_manual_group(running: dict) -> None:
    record = read_record(running["output_dir"])
    metrics = record["study_metrics"]
    assert metrics["processing_hook_connected"] is False
    assert metrics["manual_review_completed"] is True
    assert metrics["manual_step_count"] is None
    assert metrics["pending_reasons"] == ["processing_history_unavailable"]
    assert len(metrics["manual_action_groups"]) == 1
    assert metrics["manual_action_groups"][0]["action_group"] == "exported GeoJSON"
    assert metrics["manual_action_groups"][0]["tool"] == "qgis:save-features-as"


@given("another component listens to processing history changes")
def other_processing_listener(host: dict) -> None:
    received: list[str] = []

    def listener(_entry_id, entry, _backend) -> None:
        received.append(entry.entry["algorithm_id"])

    host["history"].entryAdded.connect(listener)
    host["other_processing_received"] = received
    host["other_processing_listener"] = listener


@when(
    parsers.parse('a processing execution for "{algorithm_id}" is queued'),
    target_fixture="queued_changes",
)
def processing_execution_is_queued(host: dict, algorithm_id: str) -> list:
    return [
        host["history"].queue_entry(
            "processing", {"algorithm_id": algorithm_id, "parameters": {"INPUT": "poland"}}
        )
    ]


@when(parsers.parse('I start another session and execute processing algorithm "{algorithm_id}"'))
def start_another_and_run_processing(
    reloaded: dict, host: dict, task_suite: Path, algorithm_id: str
) -> None:
    reply = _start(reloaded["handle"], DEMO_TASK_ID, task_suite)
    assert reply.startswith("session started for task"), reply
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    reloaded["output_dir"] = recorder.output_dir
    host["history"].add_entry("processing", {"algorithm_id": algorithm_id, "parameters": {}})


@then("the processing history listener is disconnected")
def processing_listener_disconnected(host: dict) -> None:
    assert not host["history"].entryAdded.slots


@then(parsers.parse('the new session alone records processing execution "{algorithm_id}"'))
def new_session_alone_records_processing(
    host: dict, running: dict, new_take: Path, algorithm_id: str
) -> None:
    assert new_take != running["output_dir"]
    events = [e for e in read_events(new_take) if e["event"] == "processing_algorithm"]
    assert [e["algorithm_id"] for e in events] == [algorithm_id]
    assert len(host["history"].entryAdded.slots) == 1


@then(parsers.parse('only the reloaded session records processing execution "{algorithm_id}"'))
def reloaded_session_records_processing(running: dict, reloaded: dict, algorithm_id: str) -> None:
    assert reloaded["output_dir"] != running["output_dir"]
    events = [
        e for e in read_events(reloaded["output_dir"]) if e["event"] == "processing_algorithm"
    ]
    assert [e["algorithm_id"] for e in events] == [algorithm_id]


@then("the other component still receives the processing history entry")
def other_processing_listener_receives_entry(host: dict) -> None:
    assert host["other_processing_received"] == ["native:buffer"]


@then("no session processing listener remains connected")
def no_session_processing_listener_remains(host: dict) -> None:
    assert host["history"].entryAdded.slots == [host["other_processing_listener"]]


@given("a QGIS 4 host reporting versions for QGIS, GDAL, GEOS, and PROJ", target_fixture="host")
def qgis4_host_with_versions(monkeypatch: pytest.MonkeyPatch) -> dict:
    import sys
    import types

    for key in ("QGIS_VERSION", "GDAL_VERSION", "GEOS_VERSION", "PROJ_VERSION"):
        monkeypatch.delenv(key, raising=False)
    project = FakeProject("readProject")
    canvas = FakeCanvas()
    install_host(monkeypatch, project=project, canvas=lambda: canvas)

    class FakeQgis:
        @staticmethod
        def version() -> str:
            return "4.2.3-Belém do Pará"

        @staticmethod
        def geosVersion() -> str:
            return "3.14.1-CAPI-1.20.5"

    sys.modules["qgis.core"].Qgis = FakeQgis

    osgeo_pkg = types.ModuleType("osgeo")
    gdal_mod = types.ModuleType("osgeo.gdal")
    gdal_mod.VersionInfo = lambda req="RELEASE_NAME": "3.13.3" if req == "RELEASE_NAME" else "31303"
    osr_mod = types.ModuleType("osgeo.osr")
    osr_mod.GetPROJVersionMajor = lambda: 9
    osr_mod.GetPROJVersionMinor = lambda: 9
    osr_mod.GetPROJVersionMicro = lambda: 0
    osgeo_pkg.gdal = gdal_mod
    osgeo_pkg.osr = osr_mod
    monkeypatch.setitem(sys.modules, "osgeo", osgeo_pkg)
    monkeypatch.setitem(sys.modules, "osgeo.gdal", gdal_mod)
    monkeypatch.setitem(sys.modules, "osgeo.osr", osr_mod)
    return {"project": project, "canvas": canvas}


@then("the record captures the QGIS, GDAL, GEOS, and PROJ versions")
def record_captures_qgis4_versions(running: dict) -> None:
    record = read_record(running["output_dir"])
    assert record["session"]["software_versions"] == {
        "qgis": "4.2.3-Belém do Pará",
        "gdal": "3.13.3",
        "geos": "3.14.1-CAPI-1.20.5",
        "proj": "9.9.0",
    }


@then("the record leaves host software versions as null")
def record_leaves_software_versions_null(running: dict) -> None:
    record = read_record(running["output_dir"])
    assert record["session"]["software_versions"] == {
        "qgis": None,
        "gdal": None,
        "geos": None,
        "proj": None,
    }


@given(
    "no EXPERIMENT_TASK_DIR is configured and cwd is nested inside a task checkout",
    target_fixture="checkout",
)
def nested_checkout_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from plugin_harness import DEMO_MANIFEST

    repo = tmp_path / "checkout"
    tasks_dir = repo / "experiment" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / f"{DEMO_TASK_ID}.yaml").write_text(DEMO_MANIFEST, encoding="utf-8")
    (tasks_dir / "fixture.geojson").write_text("{}", encoding="utf-8")
    nested = repo / "experiment-qgis-plugin" / "subdir"
    nested.mkdir(parents=True)
    monkeypatch.delenv("EXPERIMENT_TASK_DIR", raising=False)
    monkeypatch.chdir(nested)
    return repo


@when(
    parsers.parse('I start a session using the default task directory for task "{task_id}"'),
    target_fixture="started",
)
def start_session_default_task_dir(loaded: PluginHandle, task_id: str) -> dict:
    reply = loaded.call("start_session", task_id=task_id, base_dir="")
    recorder = plugin._ACTIVE["session"]
    return {
        "reply": reply,
        "output_dir": recorder.output_dir if recorder else None,
        "recorder": recorder,
    }


@when(
    parsers.parse('I start a session for task "{task_id}" with a missing task directory'),
    target_fixture="started",
)
def start_session_missing_task_dir(loaded: PluginHandle, tmp_path: Path, task_id: str) -> dict:
    missing = tmp_path / "does-not-exist" / "tasks"
    reply = loaded.call("start_session", task_id=task_id, base_dir=str(missing))
    recorder = plugin._ACTIVE["session"]
    return {
        "reply": reply,
        "output_dir": recorder.output_dir if recorder else None,
        "recorder": recorder,
    }


@then("the started session belongs to that checkout's baselines folder")
def started_session_belongs_to_checkout(started: dict, checkout: Path) -> None:
    assert started["recorder"] is not None, started["reply"]
    expected = (checkout / "experiment" / "tasks" / "baselines" / DEMO_TASK_ID).resolve()
    assert started["output_dir"].parent == expected


@then("the plugin explains that the task directory does not exist and mentions EXPERIMENT_TASK_DIR")
def plugin_explains_missing_task_dir(started: dict) -> None:
    assert started["recorder"] is None
    assert "cannot start session:" in started["reply"]
    assert "task directory does not exist" in started["reply"]
    assert "EXPERIMENT_TASK_DIR" in started["reply"]


@when("the participant saves top-level and nested output files into the session directory")
def participant_saves_nested_outputs(running: dict) -> None:
    root = running["output_dir"]
    (root / "summary.geojson").write_text('{"type": "FeatureCollection"}\n', encoding="utf-8")
    bundle = root / "shapefile" / "poland"
    bundle.mkdir(parents=True)
    (bundle / "layer.shp").write_bytes(b"\x00\x01\x02shp")
    (bundle / "layer.prj").write_text("EPSG:2180\n", encoding="utf-8")


@then("the record hashes both top-level and nested output files with relative POSIX paths")
def record_hashes_nested_outputs(running: dict) -> None:
    import hashlib

    record = read_record(running["output_dir"])
    paths = [output["path"] for output in record["outputs"]]
    assert paths == [
        "shapefile/poland/layer.prj",
        "shapefile/poland/layer.shp",
        "summary.geojson",
    ]
    for output in record["outputs"]:
        disk_path = running["output_dir"] / output["path"]
        assert output["sha256"] == hashlib.sha256(disk_path.read_bytes()).hexdigest()
        assert output["bytes"] == disk_path.stat().st_size


@then("the session is still running")
def the_session_is_still_running(loaded: PluginHandle) -> None:
    reply = loaded.call("start_session", task_id="another-task")
    assert reply.startswith("session already active")


# --- bind the feature files -------------------------------------------------

for _feature in (
    "hello.feature",
    "human-baseline.feature",
    "session-panel.feature",
    "host-observation.feature",
):
    scenarios(str(FEATURE_DIR / _feature))
