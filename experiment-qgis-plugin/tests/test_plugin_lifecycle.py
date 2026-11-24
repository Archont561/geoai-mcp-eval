"""Defensive lifecycle tests that need an in-flight host callback."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest
from plugin_harness import (
    DEMO_TASK_ID,
    FakeCanvas,
    FakeHistoryRegistry,
    FakeProject,
    install_host,
    read_events,
)
from qgis_sdk.ui.actions import ViewActions

from experiment_plugin import plugin


def test_closing_the_starting_view_keeps_the_session_observing(
    monkeypatch, loaded_plugin, task_suite
) -> None:
    project, canvas = FakeProject(), FakeCanvas()
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    runtime = loaded_plugin.plugin.runtime
    view_scope = runtime.context.scope.child()
    actions = ViewActions(runtime, view_id="session-panel", scope=view_scope)
    actions.start_session(task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None

    view_scope.close()
    project.layersAdded.fire(["a"])
    canvas.scaleChanged.fire(50000.0)
    assert [event["event"] for event in read_events(recorder.output_dir)] == [
        "session_start",
        "layers_added",
        "canvas_scale",
    ]
    assert loaded_plugin.call("end_session").startswith("session ended")


def test_inflight_host_observation_finishes_before_the_session_ends(
    monkeypatch, loaded_plugin, task_suite
) -> None:
    project = FakeProject()
    canvas = FakeCanvas()
    entered = Event()
    release = Event()
    extent = canvas.extent

    def blocked_extent():
        entered.set()
        if not release.wait(5):
            raise TimeoutError("host callback did not resume")
        return extent()

    monkeypatch.setattr(canvas, "extent", blocked_extent)
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    loaded_plugin.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        observation = pool.submit(canvas.extentsChanged.fire)
        try:
            assert entered.wait(5)
            ending = pool.submit(loaded_plugin.call, "end_session")
            with pytest.raises(TimeoutError):
                ending.result(timeout=0.2)
        finally:
            release.set()
        observation.result(timeout=5)
        assert ending.result(timeout=5).startswith("session ended")

    assert [event["event"] for event in read_events(recorder.output_dir)] == [
        "session_start",
        "canvas_extent",
        "session_end",
    ]
    evidence = (recorder.output_dir / "events.jsonl").read_bytes()
    canvas.extentsChanged.fire()
    assert (recorder.output_dir / "events.jsonl").read_bytes() == evidence


def test_a_start_failure_after_connecting_hooks_releases_the_incomplete_take(
    monkeypatch, loaded_plugin, task_suite
) -> None:
    project, canvas = FakeProject(), FakeCanvas()
    connect = project.layersAdded.connect

    def remove_fixture_after_connect(slot):
        connect(slot)
        (task_suite / "fixture.geojson").unlink()

    monkeypatch.setattr(project.layersAdded, "connect", remove_fixture_after_connect)
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    with pytest.raises(FileNotFoundError):
        loaded_plugin.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))

    output_dir = next((task_suite / "baselines" / DEMO_TASK_ID).iterdir())
    before = (output_dir / "events.jsonl").read_bytes()
    project.layersAdded.fire(["a"])
    canvas.scaleChanged.fire(50000.0)
    assert (output_dir / "events.jsonl").read_bytes() == before
    assert not (output_dir / "human-reference-record.json").exists()
    assert not project.layersAdded.slots and not canvas.scaleChanged.slots
    assert loaded_plugin.call("log_note", message="late") == "no active session"


@pytest.mark.parametrize("write_first", [False, True], ids=["before-event", "after-event"])
def test_failed_terminal_write_never_promotes_incomplete_evidence(
    monkeypatch, loaded_plugin, task_suite, write_first: bool
) -> None:
    project, canvas = FakeProject(), FakeCanvas()
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    loaded_plugin.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    events_path = recorder.output_dir / "events.jsonl"
    open_file = Path.open

    @contextmanager
    def failing_open(path, mode="r", *args, **kwargs):
        with open_file(path, mode, *args, **kwargs) as handle:
            if path != events_path or mode != "a":
                yield handle
                return

            class TerminalWriter:
                def write(self, text):
                    if '"event": "session_end"' in text:
                        if write_first:
                            handle.write(text)
                            handle.flush()
                        raise OSError("terminal event write failed")
                    return handle.write(text)

            yield TerminalWriter()

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", failing_open)
        with pytest.raises(OSError, match="terminal event write failed"):
            loaded_plugin.call("end_session")

    assert not (recorder.output_dir / "human-reference-record.json").exists()
    assert not list(recorder.output_dir.glob(".human-reference-record-*.tmp"))
    if write_first:
        assert recorder.status == "incomplete"
        assert loaded_plugin.call("log_note", message="late") == "no active session"
        before = events_path.read_bytes()
        project.layersAdded.fire(["a"])
        canvas.scaleChanged.fire(50000.0)
        assert events_path.read_bytes() == before
        assert [event["event"] for event in read_events(recorder.output_dir)] == [
            "session_start",
            "session_end",
        ]
        assert not project.layersAdded.slots and not canvas.scaleChanged.slots
    else:
        project.layersAdded.fire(["a"])
        canvas.scaleChanged.fire(50000.0)
        assert [event["event"] for event in read_events(recorder.output_dir)] == [
            "session_start",
            "layers_added",
            "canvas_scale",
        ]
        assert loaded_plugin.call("end_session").startswith("session ended")
        assert (recorder.output_dir / "human-reference-record.json").exists()


def test_failed_record_publication_closes_the_incomplete_take(
    monkeypatch, loaded_plugin, task_suite
) -> None:
    project, canvas = FakeProject(), FakeCanvas()
    install_host(monkeypatch, project=project, canvas=lambda: canvas)
    loaded_plugin.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    replace = Path.replace

    def fail_publication(path, target):
        if path.name.startswith(".human-reference-record-"):
            raise OSError("record publication failed")
        return replace(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publication)
        with pytest.raises(OSError, match="record publication failed"):
            loaded_plugin.call("end_session")

    assert recorder.status == "incomplete"
    assert list(recorder.output_dir.iterdir()) == [recorder.output_dir / "events.jsonl"]
    assert [event["event"] for event in read_events(recorder.output_dir)] == [
        "session_start",
        "session_end",
    ]
    before = recorder.tracker.events_path.read_bytes()
    project.crsChanged.fire()
    assert recorder.tracker.events_path.read_bytes() == before
    assert loaded_plugin.call("log_note", message="late") == "no active session"


def test_failed_record_publication_with_processing_evidence_closes_take_and_disconnects_history(
    monkeypatch, loaded_plugin, task_suite
) -> None:
    project, canvas, history = FakeProject(), FakeCanvas(), FakeHistoryRegistry()
    install_host(monkeypatch, project=project, canvas=lambda: canvas, history_registry=history)
    loaded_plugin.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    history.add_entry(
        "processing",
        {"algorithm_id": "native:buffer", "parameters": {"DISTANCE": 5}},
    )
    replace = Path.replace

    def fail_publication(path, target):
        if path.name.startswith(".human-reference-record-"):
            raise OSError("record publication failed")
        return replace(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publication)
        with pytest.raises(OSError, match="record publication failed"):
            loaded_plugin.call("end_session", manual_review_complete=True)

    assert recorder.status == "incomplete"
    assert not (recorder.output_dir / "human-reference-record.json").exists()
    assert not history.entryAdded.slots
    before = recorder.tracker.events_path.read_bytes()
    history.add_entry("processing", {"algorithm_id": "native:clip", "parameters": {}})
    assert recorder.tracker.events_path.read_bytes() == before
