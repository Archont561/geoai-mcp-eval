"""Unit tests for the recorder's rendering and hashing.

Session behaviour — starting, noting, ending, abandoning — is specified in
``features/human-baseline.feature`` and exercised through the plugin's actions.
What remains here are cases that are not behaviour a participant can observe:
a malformed log line must survive rendering, and a deleted log must still
render something rather than raise.
"""

from __future__ import annotations

import json
from pathlib import Path

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
