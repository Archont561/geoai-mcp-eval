"""Pure tests for the human-baseline recorder — no QGIS or Qt needed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment_plugin import session

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"
UTF8 = "utf-8"


def copy_suite(tmp_path: Path) -> Path:
    for yaml_file in TASK_ROOT.glob("*.yaml"):
        (tmp_path / yaml_file.name).write_text(yaml_file.read_text(encoding=UTF8), encoding=UTF8)
    import shutil

    shutil.copytree(TASK_ROOT / "fixtures", tmp_path / "fixtures")
    return tmp_path


def test_start_log_end_roundtrip(tmp_path: Path) -> None:
    copy_suite(tmp_path)
    recorder = session.start_session(
        "prep-axis-order-001", tmp_path, participant_code="P01", network_disabled=True
    )
    recorder.log("layers_added", tool="host:project", count=1)
    recorder.log("note", tool="note", message="had to re-read the prompt")
    out_dir = recorder.output_dir
    (out_dir / "result.geojson").write_text(
        '{"type":"FeatureCollection","features":[]}', encoding=UTF8
    )

    record_path = recorder.finish()
    record = json.loads(record_path.read_text(encoding=UTF8))
    assert_record(record, out_dir)
    events = [
        json.loads(line)
        for line in (out_dir / "events.jsonl").read_text(encoding=UTF8).splitlines()
        if line
    ]
    assert events[0]["event"] == "session_start"
    assert events[-1]["event"] == "session_end"
    assert len(events) == 4  # session_start + 2 logged + session_end


def assert_record(record: dict, out_dir: Path) -> None:
    import hashlib

    assert set(session.TEMPLATE_KEYS) <= set(record)
    assert record["status"] == "recorded"
    assert record["task_id"] == "prep-axis-order-001"
    assert len(record["task_file_sha256"]) == 64
    assert len(record["fixture_sha256"]) == 64
    assert record["participant_code"] == "P01"
    assert record["session"]["network_disabled"] is True
    assert record["session"]["steps"] == 2  # start/end markers are not steps
    assert set(record["session"]["tools"]) == {"host:project", "note"}
    assert record["session"]["elapsed_minutes"] >= 0
    outputs = {o["path"]: o for o in record["outputs"]}
    assert "result.geojson" in outputs
    assert (
        outputs["result.geojson"]["sha256"]
        == hashlib.sha256((out_dir / "result.geojson").read_bytes()).hexdigest()
    )


def test_unknown_task_id_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        session.start_session("no-such-task", tmp_path)


def test_finish_hashes_every_output_file(tmp_path: Path) -> None:
    for yaml_file in TASK_ROOT.glob("*.yaml"):
        (tmp_path / yaml_file.name).write_text(yaml_file.read_text(encoding=UTF8), encoding=UTF8)
    import shutil

    shutil.copytree(TASK_ROOT / "fixtures", tmp_path / "fixtures")
    recorder = session.start_session("analysis-de9im-001", tmp_path)
    (recorder.output_dir / "result.json").write_text(
        '{"relation":"touches","de9im":"FF2F11212"}', encoding=UTF8
    )
    record_path = recorder.finish()
    record = json.loads(record_path.read_text(encoding=UTF8))
    assert [o["path"] for o in record["outputs"]] == ["result.json"]


def test_empty_participant_code_becomes_none(tmp_path: Path) -> None:
    for yaml_file in TASK_ROOT.glob("*.yaml"):
        (tmp_path / yaml_file.name).write_text(yaml_file.read_text(encoding=UTF8), encoding=UTF8)
    import shutil

    shutil.copytree(TASK_ROOT / "fixtures", tmp_path / "fixtures")
    recorder = session.start_session("cartography-jenks-001", tmp_path, participant_code="")
    record = json.loads(recorder.finish().read_text(encoding=UTF8))
    assert record["participant_code"] is None


def test_network_disabled_defaults_to_none(tmp_path: Path) -> None:
    copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", tmp_path)
    record = json.loads(recorder.finish().read_text(encoding=UTF8))
    assert record["session"]["network_disabled"] is None


def test_same_second_restarts_get_distinct_session_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_suite(tmp_path)
    from datetime import UTC, datetime

    fixed = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(session, "utc_now", lambda: fixed)
    first = session.start_session("prep-axis-order-001", tmp_path)
    second = session.start_session("prep-axis-order-001", tmp_path)
    assert first.output_dir != second.output_dir
    assert first.output_dir.name == "session-20261122T100000Z"
    assert second.output_dir.name == "session-20261122T100000Z-2"
    assert (first.output_dir / "events.jsonl").read_text(encoding=UTF8) != ""
    assert (second.output_dir / "events.jsonl").exists()


def test_render_log_renders_events_and_header(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite, participant_code="P1")
    recorder.log("note", tool="note", message="hello world")
    text = session.render_log(recorder)
    lines = text.splitlines()
    assert lines[0].startswith("human-baseline session log")
    assert "prep-axis-order-001" in lines[0]
    assert any("status: in_progress" in line for line in lines)
    assert any("session_start" in line and "task_id=prep-axis-order-001" in line for line in lines)
    note_line = next(line for line in lines if "note" in line and "hello world" in line)
    assert "message=hello world" in note_line


def test_render_log_passes_through_malformed_lines(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    with recorder.tracker.events_path.open("a", encoding="utf-8") as handle:
        handle.write("this is not json\n")
    text = session.render_log(recorder)
    assert "this is not json" in text


def test_render_log_reports_missing_event_log(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    recorder.tracker.events_path.unlink()
    text = session.render_log(recorder)
    assert "(event log unavailable:" in text


def test_abandon_session_marks_evidence_without_record(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite, participant_code="P1")
    recorder.log("note", tool="note", message="mid-take")
    marker = session.abandon_session(recorder, reason="restart requested")
    assert recorder.status == "abandoned"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["record_written"] is False
    assert payload["reason"] == "restart requested"
    assert payload["task_id"] == "prep-axis-order-001"
    assert payload["tools_used"] == ["note"]
    assert not (recorder.output_dir / "human-reference-record.json").exists()
    events = recorder.tracker.events_path.read_text(encoding="utf-8")
    assert "session_abandoned" in events
    assert "restart requested" in events
