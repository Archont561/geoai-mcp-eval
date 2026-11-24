"""Gherkin scenario bindings for non-destructive post-session review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from plugin_harness import (
    DEMO_TASK_ID,
    FakeCanvas,
    FakeHistoryRegistry,
    FakeProject,
    PluginHandle,
    install_host,
)
from pytest_bdd import given, parsers, scenarios, then, when

from experiment_plugin import plugin, review

FEATURE_DIR = Path(__file__).resolve().parent.parent / "features"


@pytest.fixture
def review_state() -> dict:
    return {}


@given("the Experiment Plugin is loaded", target_fixture="loaded")
def plugin_is_loaded(session_store):
    handle = PluginHandle()
    yield handle
    handle.unload()


@given("the pilot task suite is available", target_fixture="suite")
def pilot_task_suite_is_available(task_suite: Path) -> Path:
    return task_suite


@given(
    "a recorded session with processing history, raw host observations, and a note",
    target_fixture="recorded_take",
)
def recorded_take_with_processing(
    loaded: PluginHandle,
    suite: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    project = FakeProject("layersAdded")
    canvas = FakeCanvas()
    history = FakeHistoryRegistry()
    install_host(monkeypatch, project=project, canvas=lambda: canvas, history_registry=history)

    loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    session_dir = recorder.output_dir

    project.layersAdded.fire(["layer-a"])
    canvas.extentsChanged.fire()
    loaded.call("log_note", message="checked CRS before exporting")
    history.add_entry(
        "processing",
        {"algorithm_id": "native:reprojectlayer", "parameters": {"TARGET_CRS": "EPSG:2180"}},
        timestamp="2026-11-24T12:00:05+00:00",
    )
    (session_dir / "result.geojson").write_text('{"type":"FeatureCollection"}\n', encoding="utf-8")
    loaded.call("end_session")

    raw_record_bytes = (session_dir / "human-reference-record.json").read_bytes()
    raw_events_bytes = (session_dir / "events.jsonl").read_bytes()
    initial_files = sorted(p.name for p in session_dir.iterdir())
    return {
        "session_dir": session_dir,
        "raw_record_bytes": raw_record_bytes,
        "raw_events_bytes": raw_events_bytes,
        "initial_files": initial_files,
    }


@given(
    "a recorded session captured without processing history coverage",
    target_fixture="recorded_take",
)
def recorded_take_without_processing(
    loaded: PluginHandle,
    suite: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    project = FakeProject("layersAdded")
    install_host(monkeypatch, project=project, canvas=None, history_registry=None)

    loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    session_dir = recorder.output_dir
    project.layersAdded.fire(["layer-a"])
    loaded.call("end_session")

    return {
        "session_dir": session_dir,
        "raw_record_bytes": (session_dir / "human-reference-record.json").read_bytes(),
        "raw_events_bytes": (session_dir / "events.jsonl").read_bytes(),
        "initial_files": sorted(p.name for p in session_dir.iterdir()),
    }


@given(
    "an external QGIS processing log with one buffer execution",
    target_fixture="processing_log_file",
)
def external_processing_log(tmp_path: Path) -> Path:
    log_path = tmp_path / "processing.log"
    log_path.write_text(
        "INFO|2026-11-24 12:00:01|Processing started\n"
        "ALGORITHM|2026-11-24 12:01:15|processing.run("
        "\"native:buffer\", {'INPUT': 'in.geojson', 'DISTANCE': 500})\n",
        encoding="utf-8",
    )
    return log_path


@given("an abandoned session on disk", target_fixture="recorded_take")
def abandoned_session_on_disk(loaded: PluginHandle, suite: Path) -> dict:
    loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    session_dir = recorder.output_dir
    loaded.call("abandon_session")
    return {"session_dir": session_dir}


@when(
    parsers.parse(
        'I review that session adding manual action "{action_group}" '
        'with tool "{tool}" and mark review complete'
    )
)
def review_with_manual_action_and_tool(
    loaded: PluginHandle,
    recorded_take: dict,
    review_state: dict,
    action_group: str,
    tool: str,
) -> None:
    reply = loaded.call(
        "review_session",
        session_dir=str(recorded_take["session_dir"]),
        manual_actions=[{"action_group": action_group, "tool": tool}],
        mark_reviewed=True,
        reviewer="coder-1",
        notes="verified against screen capture",
    )
    review_state["reply"] = reply
    review_state["output_dir"] = recorded_take["session_dir"]


@when(
    parsers.parse(
        'I review that session adding manual action "{action_group}" '
        "without marking review complete"
    )
)
def review_draft_without_complete(
    loaded: PluginHandle,
    recorded_take: dict,
    review_state: dict,
    action_group: str,
) -> None:
    reply = loaded.call(
        "review_session",
        session_dir=str(recorded_take["session_dir"]),
        manual_actions=[{"action_group": action_group}],
        mark_reviewed=False,
        reviewer="coder-1",
    )
    review_state["reply"] = reply
    review_state["output_dir"] = recorded_take["session_dir"]


@when("I review that session with the external processing log and mark review complete")
def review_with_external_processing_log(
    loaded: PluginHandle,
    recorded_take: dict,
    processing_log_file: Path,
    review_state: dict,
) -> None:
    reply = loaded.call(
        "review_session",
        session_dir=str(recorded_take["session_dir"]),
        processing_log=str(processing_log_file),
        mark_reviewed=True,
        reviewer="coder-1",
    )
    review_state["reply"] = reply
    review_state["output_dir"] = recorded_take["session_dir"]
    review_state["processing_log_file"] = processing_log_file


@when("I attempt to review that abandoned session")
def attempt_review_abandoned(loaded: PluginHandle, recorded_take: dict, review_state: dict) -> None:
    reply = loaded.call(
        "review_session",
        session_dir=str(recorded_take["session_dir"]),
        mark_reviewed=True,
    )
    review_state["reply"] = reply
    review_state["output_dir"] = recorded_take["session_dir"]


@when("I run the review CLI targeting a separate output directory and marking review complete")
def run_review_cli_separate_output(recorded_take: dict, tmp_path: Path, review_state: dict) -> None:
    out_dir = tmp_path / "reviewed-export"
    exit_code = review.main(
        [
            str(recorded_take["session_dir"]),
            "--manual-action",
            "exported GeoJSON",
            "--tool",
            "qgis:save-features-as",
            "--reviewer",
            "coder-cli",
            "--notes",
            "audited via CLI",
            "--mark-reviewed",
            "--output-dir",
            str(out_dir),
        ]
    )
    review_state["exit_code"] = exit_code
    review_state["output_dir"] = out_dir


@then("the original raw record and event log are byte-for-byte unchanged")
def original_raw_files_unchanged(recorded_take: dict) -> None:
    session_dir = recorded_take["session_dir"]
    assert (session_dir / "human-reference-record.json").read_bytes() == recorded_take[
        "raw_record_bytes"
    ]
    assert (session_dir / "events.jsonl").read_bytes() == recorded_take["raw_events_bytes"]


@then(
    parsers.parse(
        'the reviewed record marks study metrics reviewed with {steps:d} steps and tools "{tools}"'
    )
)
def reviewed_record_marks_reviewed(review_state: dict, steps: int, tools: str) -> None:
    record = json.loads(
        (review_state["output_dir"] / "human-reference-record.reviewed.json").read_text(
            encoding="utf-8"
        )
    )
    expected_tools = [item.strip() for item in tools.split(",") if item.strip()]
    assert record["session"]["metrics_status"] == "reviewed"
    assert record["study_metrics"]["status"] == "reviewed"
    assert record["study_metrics"]["pending_reasons"] == []
    assert record["session"]["steps"] == steps
    assert record["session"]["tools"] == expected_tools


@then("the reviewed record pins SHA-256 hashes of the raw record and event log")
def reviewed_record_pins_source_hashes(recorded_take: dict, review_state: dict) -> None:
    record = json.loads(
        (review_state["output_dir"] / "human-reference-record.reviewed.json").read_text(
            encoding="utf-8"
        )
    )
    prov = record["review"]
    assert prov["reviewer"] == "coder-1"
    assert prov["notes"] == "verified against screen capture"
    assert (
        prov["source_record_sha256"]
        == hashlib.sha256(recorded_take["raw_record_bytes"]).hexdigest()
    )
    assert (
        prov["source_events_sha256"]
        == hashlib.sha256(recorded_take["raw_events_bytes"]).hexdigest()
    )


@then(parsers.parse("human_trajectory.jsonl contains only the {count:d} audited study steps"))
def trajectory_contains_only_audited_steps(review_state: dict, count: int) -> None:
    lines = (
        (review_state["output_dir"] / "human_trajectory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    entries = [json.loads(line) for line in lines if line.strip()]
    assert len(entries) == count
    assert [entry["kind"] for entry in entries] == [
        "processing_execution",
        "manual_action_group",
    ]
    assert entries[0]["algorithm_id"] == "native:reprojectlayer"
    assert entries[1]["action_group"] == "exported GeoJSON"
    assert entries[1]["tool"] == "qgis:save-features-as"
    valid_kinds = {"processing_execution", "manual_action_group"}
    assert all(entry["kind"] in valid_kinds for entry in entries)


@then(parsers.parse('the reviewed record keeps study metrics pending review for reason "{reason}"'))
def reviewed_record_keeps_pending_for_reason(review_state: dict, reason: str) -> None:
    record = json.loads(
        (review_state["output_dir"] / "human-reference-record.reviewed.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["session"]["metrics_status"] == "pending_review"
    assert record["study_metrics"]["status"] == "pending_review"
    assert reason in record["study_metrics"]["pending_reasons"]


@then("the reviewed record leaves study steps and tools null")
def reviewed_record_leaves_steps_and_tools_null(review_state: dict) -> None:
    record = json.loads(
        (review_state["output_dir"] / "human-reference-record.reviewed.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["session"]["steps"] is None
    assert record["session"]["tools"] is None


@then(parsers.parse("the reviewed record retains {count:d} manual action group with null tool"))
def reviewed_record_retains_manual_action_null_tool(review_state: dict, count: int) -> None:
    record = json.loads(
        (review_state["output_dir"] / "human-reference-record.reviewed.json").read_text(
            encoding="utf-8"
        )
    )
    groups = record["study_metrics"]["manual_action_groups"]
    assert len(groups) == count
    assert groups[0]["tool"] is None


@then("the reviewed record records the processing log SHA-256")
def reviewed_record_records_processing_log_sha(review_state: dict) -> None:
    record = json.loads(
        (review_state["output_dir"] / "human-reference-record.reviewed.json").read_text(
            encoding="utf-8"
        )
    )
    expected = hashlib.sha256(review_state["processing_log_file"].read_bytes()).hexdigest()
    assert record["review"]["processing_log_sha256"] == expected


@then("human_trajectory.jsonl contains the parsed processing log execution")
def trajectory_contains_processing_log_execution(review_state: dict) -> None:
    lines = (
        (review_state["output_dir"] / "human_trajectory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    entries = [json.loads(line) for line in lines if line.strip()]
    assert len(entries) == 1
    assert entries[0]["kind"] == "processing_execution"
    assert entries[0]["origin"] == "processing_log"
    assert entries[0]["algorithm_id"] == "native:buffer"
    assert entries[0]["parameters"] == {"DISTANCE": 500, "INPUT": "in.geojson"}


@then("the review is refused as an abandoned take")
def review_refused_as_abandoned(review_state: dict) -> None:
    assert "cannot review session:" in review_state["reply"]
    assert "abandoned" in review_state["reply"].lower()


@then("no reviewed record or trajectory file is written")
def no_reviewed_files_written(review_state: dict) -> None:
    out_dir = review_state["output_dir"]
    assert not (out_dir / "human-reference-record.reviewed.json").exists()
    assert not (out_dir / "human_trajectory.jsonl").exists()


@then("the review CLI exits successfully")
def review_cli_exits_zero(review_state: dict) -> None:
    assert review_state["exit_code"] == 0


@then("the separate output directory contains the reviewed record and human_trajectory.jsonl")
def separate_output_contains_reviewed_files(review_state: dict) -> None:
    out_dir = review_state["output_dir"]
    assert (out_dir / "human-reference-record.reviewed.json").is_file()
    assert (out_dir / "human_trajectory.jsonl").is_file()


@then("the original session directory contains no new files")
def original_session_dir_has_no_new_files(recorded_take: dict) -> None:
    current_files = sorted(p.name for p in recorded_take["session_dir"].iterdir())
    assert current_files == recorded_take["initial_files"]


scenarios(str(FEATURE_DIR / "post-session-review.feature"))
