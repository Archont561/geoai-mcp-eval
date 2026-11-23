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

from pathlib import Path

import pytest
from plugin_harness import (
    DEMO_TASK_ID,
    FakeCanvas,
    FakeFileDialog,
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


@given("a session is active with two logged events", target_fixture="running")
def a_session_with_two_events(loaded: PluginHandle, raw_task_suite) -> dict:
    _start(loaded, DEMO_TASK_ID, raw_task_suite)
    recorder = plugin._ACTIVE["session"]
    recorder.log("layers_added", tool="host:project", count=1)
    recorder.log("note", tool="note", message="mid-take")
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


@then("the record's step count excludes the start and end markers")
def the_step_count_excludes_markers(running: dict) -> None:
    record = read_record(running["output_dir"])
    assert record["session"]["steps"] == 2
    assert set(record["session"]["tools"]) == {"host:project", "note"}


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
    FakeMessageBox._answer = FakeMessageBox.StandardButton.Yes
    panel_state["dialog"]._parts["restart_button"].click()
    return {**panel_state, "previous": previous}


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
    return {"recorder": recorder, "output_dir": recorder.output_dir}


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
    assert events[-1]["path"] == "/tmp/fake-project.qgs"


@then("the project read hook is wired")
def project_read_wired(host: dict, running: dict) -> None:
    assert len(host["project"].projectRead.slots) == 1


@then("the start message reports the missing project read hook")
def start_message_reports_missing_hook(running: dict) -> None:
    recorder = running["recorder"]
    assert "project_read" in " ".join(plugin._connect_host_hooks(recorder)[1])


@then("the layer and CRS hooks are still wired")
def layers_and_crs_still_wired(host: dict) -> None:
    project = host["project"]
    assert project.layersAdded.slots
    assert project.crsChanged.slots


@then("the event log records the extent and the scale")
def log_records_extent_and_scale(host: dict) -> None:
    events = read_events(host["running"]["output_dir"])
    extent = [e for e in events if e["event"] == "canvas_extent"]
    scale = [e for e in events if e["event"] == "canvas_scale"]
    assert extent and scale
    assert scale[-1]["scale"] == 50000.0


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
    assert "canvas:" in started["reply"]


@then("the session is still running")
def the_session_is_still_running() -> None:
    assert plugin._ACTIVE["session"] is not None


# --- bind the feature files -------------------------------------------------

for _feature in (
    "hello.feature",
    "human-baseline.feature",
    "session-panel.feature",
    "host-observation.feature",
):
    scenarios(str(FEATURE_DIR / _feature))
