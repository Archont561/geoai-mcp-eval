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


# Translate reviewer-facing vocabulary into the concrete review inputs.


scenarios(str(FEATURE_DIR / "post-session-review.feature"))

# Step definitions follow feature and scenario order; shared steps appear at first use.

# post-session-review.feature — Background


@given("the Experiment Plugin is loaded", target_fixture="loaded")
def plugin_is_loaded(session_store):
    handle = PluginHandle()
    yield handle
    handle.unload()


@given("the pilot task suite is available", target_fixture="suite")
def pilot_task_suite_is_available(task_suite: Path) -> Path:
    return task_suite


# post-session-review.feature — A reviewer adds an export to a recorded session


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


@when("I complete a review adding a manually performed export")
def complete_export_review(loaded, recorded_take, review_state) -> None:
    review_with_manual_action_and_tool(
        loaded, recorded_take, review_state, "exported GeoJSON", "qgis:save-features-as"
    )


@then("the original raw record and event log are byte-for-byte unchanged")
def original_raw_files_unchanged(recorded_take: dict) -> None:
    session_dir = recorded_take["session_dir"]
    assert (session_dir / "human-reference-record.json").read_bytes() == recorded_take[
        "raw_record_bytes"
    ]
    assert (session_dir / "events.jsonl").read_bytes() == recorded_take["raw_events_bytes"]


@then("the reviewed record reports two steps and both observed tools")
def reviewed_two_steps(review_state) -> None:
    reviewed_record_marks_reviewed(review_state, 2, "native:reprojectlayer, qgis:save-features-as")


@then("the reviewed record identifies the original evidence by its fingerprints")
def original_evidence_fingerprints(recorded_take, review_state) -> None:
    reviewed_record_pins_source_hashes(recorded_take, review_state)


@then("the reviewed trajectory contains only the two audited study steps")
def reviewed_two_step_trajectory(review_state) -> None:
    trajectory_contains_only_audited_steps(review_state, 2)


# post-session-review.feature — A reviewer supplies an external processing history


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


@then("the reviewed record reports one buffer step and its tool")
def reviewed_buffer_step(review_state) -> None:
    reviewed_record_marks_reviewed(review_state, 1, "native:buffer")


@then("the reviewed record identifies the external processing log")
def external_log_fingerprint(review_state) -> None:
    reviewed_record_records_processing_log_sha(review_state)


@then("the reviewed trajectory contains the external processing execution")
def external_processing_trajectory(review_state) -> None:
    trajectory_contains_processing_log_execution(review_state)


# post-session-review.feature — An empty processing history supports a fully manual workflow


@given("an empty external processing history", target_fixture="processing_log_file")
def empty_processing_history(tmp_path: Path) -> Path:
    path = tmp_path / "processing.log"
    path.write_text("", encoding="utf-8")
    return path


@when("the reviewer completes a manual-only review")
def complete_manual_only_review(
    loaded: PluginHandle, recorded_take: dict, processing_log_file: Path, review_state: dict
) -> None:
    review_state["reply"] = loaded.call(
        "review_session",
        session_dir=str(recorded_take["session_dir"]),
        manual_actions=[{"action_group": "digitized boundary manually"}],
        processing_log=str(processing_log_file),
        mark_reviewed=True,
    )
    review_state["output_dir"] = recorded_take["session_dir"]


@then("the reviewed record reports one manual step and no tools")
def reviewed_manual_step_no_tools(review_state: dict) -> None:
    record = json.loads((review_state["output_dir"] / review.REVIEWED_RECORD_FILENAME).read_text())
    assert record["session"]["metrics_status"] == "reviewed"
    assert record["session"]["steps"] == 1
    assert record["session"]["tools"] == []
    entries = [
        json.loads(line)
        for line in (review_state["output_dir"] / "human_trajectory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(entries) == 1
    assert entries[0]["kind"] == "manual_action_group"
    assert entries[0]["tool"] is None


# post-session-review.feature — Repeating a review does not duplicate matching processing evidence


@given(
    "an external history matching its recorded processing execution",
    target_fixture="processing_log_file",
)
def matching_processing_history(tmp_path: Path) -> Path:
    path = tmp_path / "processing.log"
    path.write_text(
        'ALGORITHM|2026-11-24T12:00:05+00:00|processing.run("native:reprojectlayer", '
        "{'TARGET_CRS': 'EPSG:2180'})\n",
        encoding="utf-8",
    )
    return path


@when("the reviewer repeats the same completed review")
def repeat_review(recorded_take: dict, processing_log_file: Path, review_state: dict) -> None:
    results = []
    for _ in range(2):
        results.append(
            review.review_session(
                recorded_take["session_dir"],
                manual_actions=[{"action_group": "saved output", "tool": "qgis:save-features-as"}],
                processing_log=processing_log_file,
                mark_reviewed=True,
            )
        )
    review_state["results"] = results


@then("the reviewed trajectory retains only one copy of the execution and one manual action")
def repeated_review_deduplicates(review_state: dict) -> None:
    first, second = review_state["results"]
    assert first.record["session"]["steps"] == 2
    assert second.record["session"]["steps"] == 2
    assert len(second.trajectory_entries) == 2


# post-session-review.feature — Review keeps manual actions recorded during the session


@given(
    "a recorded session with a manual styling action and processing history",
    target_fixture="recorded_take",
)
def session_with_manual_styling(
    loaded: PluginHandle, suite: Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    project, canvas, history = FakeProject(), FakeCanvas(), FakeHistoryRegistry()
    install_host(monkeypatch, project=project, canvas=lambda: canvas, history_registry=history)
    loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    loaded.call("log_manual_action", action_group="styled layer")
    loaded.call("end_session")
    return {"session_dir": recorder.output_dir}


@then("the review counts both manual actions and attributes only the export tool")
def manual_actions_and_origins_preserved(review_state: dict) -> None:
    path = review_state["output_dir"]
    record = json.loads((path / review.REVIEWED_RECORD_FILENAME).read_text(encoding="utf-8"))
    entries = [
        json.loads(line)
        for line in (path / "human_trajectory.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert record["session"]["steps"] == 2
    assert record["session"]["tools"] == ["qgis:save-features-as"]
    assert [entry["origin"] for entry in entries] == ["session_manual", "post_session_review"]


# post-session-review.feature — A reviewer writes the results to a separate location


@when("I complete a review in a separate output directory")
def complete_review_separately(recorded_take, tmp_path, review_state) -> None:
    run_review_cli_separate_output(recorded_take, tmp_path, review_state)


@then("the review succeeds")
def review_succeeds(review_state) -> None:
    review_cli_exits_zero(review_state)


@then("the separate output directory contains the reviewed record and trajectory")
def separate_review_outputs(review_state) -> None:
    separate_output_contains_reviewed_files(review_state)


@then("the original session directory contains no new files")
def original_session_dir_has_no_new_files(recorded_take: dict) -> None:
    current_files = sorted(p.name for p in recorded_take["session_dir"].iterdir())
    assert current_files == recorded_take["initial_files"]


# post-session-review.feature — A draft retains the reviewer's action but leaves metrics pending


@when("I add a manual inspection without completing the review")
def draft_inspection_review(loaded, recorded_take, review_state) -> None:
    review_draft_without_complete(loaded, recorded_take, review_state, "inspected layer CRS")


@then("the reviewed record says manual review is pending")
def manual_review_pending(review_state) -> None:
    reviewed_record_keeps_pending_for_reason(review_state, "manual_review_pending")


@then("the reviewed record retains one manual action without a named tool")
def manual_action_without_tool(review_state) -> None:
    reviewed_record_retains_manual_action_null_tool(review_state, 1)


# post-session-review.feature — Missing processing history leaves metrics pending


@then("the reviewed record says processing history is unavailable")
def processing_history_unavailable(review_state) -> None:
    reviewed_record_keeps_pending_for_reason(review_state, "processing_history_unavailable")


@then("the reviewed record leaves study steps and tools unknown")
def unknown_study_metrics(review_state) -> None:
    reviewed_record_leaves_steps_and_tools_null(review_state)


# post-session-review.feature — A damaged external processing history prevents verified metrics


@given(
    "an external processing history with an unreadable execution",
    target_fixture="processing_log_file",
)
def unreadable_processing_history(tmp_path: Path) -> Path:
    path = tmp_path / "processing.log"
    path.write_text("ALGORITHM|2026-11-24 12:03:00|corrupt-payload\n", encoding="utf-8")
    return path


@when("the reviewer completes the review using that history")
def complete_review_with_damaged_history(
    loaded: PluginHandle, recorded_take: dict, processing_log_file: Path, review_state: dict
) -> None:
    review_with_external_processing_log(loaded, recorded_take, processing_log_file, review_state)


@then("the reviewed record says processing history is incomplete")
def reviewed_processing_history_incomplete(review_state: dict) -> None:
    reviewed_record_keeps_pending_for_reason(review_state, "processing_history_incomplete")


# post-session-review.feature — A review that cannot be saved leaves no partial reviewed record


@given("the review destination cannot publish the record")
def review_record_unwritable(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from unittest.mock import MagicMock

    monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("disk full")))


@when("the reviewer tries to complete the review")
def attempt_unwritable_review(recorded_take: dict, review_state: dict) -> None:
    with pytest.raises(OSError, match="disk full") as error:
        review.review_session(recorded_take["session_dir"], mark_reviewed=True)
    review_state["error"] = error.value


@then("the save failure is reported and no partial reviewed record remains")
def failed_review_leaves_no_partial_record(recorded_take: dict, review_state: dict) -> None:
    path = recorded_take["session_dir"]
    assert "disk full" in str(review_state["error"])
    assert not list(path.glob(".human-reference-record-reviewed-*.tmp"))
    assert not (path / review.REVIEWED_RECORD_FILENAME).exists()


# post-session-review.feature — An abandoned session cannot be reviewed


@given("an abandoned session on disk", target_fixture="recorded_take")
def abandoned_session_on_disk(loaded: PluginHandle, suite: Path) -> dict:
    loaded.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(suite))
    recorder = plugin._ACTIVE["session"]
    assert recorder is not None
    session_dir = recorder.output_dir
    loaded.call("abandon_session")
    return {"session_dir": session_dir}


@when("I attempt to review that abandoned session")
def attempt_review_abandoned(loaded: PluginHandle, recorded_take: dict, review_state: dict) -> None:
    reply = loaded.call(
        "review_session",
        session_dir=str(recorded_take["session_dir"]),
        mark_reviewed=True,
    )
    review_state["reply"] = reply
    review_state["output_dir"] = recorded_take["session_dir"]


@then("the review is refused as an abandoned take")
def review_refused_as_abandoned(review_state: dict) -> None:
    assert "cannot review session:" in review_state["reply"]
    assert "abandoned" in review_state["reply"].lower()


@then("no reviewed record or trajectory file is written")
def no_reviewed_files_written(review_state: dict) -> None:
    out_dir = review_state["output_dir"]
    assert not (out_dir / "human-reference-record.reviewed.json").exists()
    assert not (out_dir / "human_trajectory.jsonl").exists()


# post-session-review.feature — Review rejects incomplete or incompatible session evidence


@given(parsers.parse("the review evidence has {problem}"))
def damage_review_evidence(
    recorded_take: dict, tmp_path: Path, review_state: dict, problem: str
) -> None:
    session_dir = recorded_take["session_dir"]
    review_state["session_dir"] = session_dir
    review_state["kwargs"] = {}
    record = session_dir / "human-reference-record.json"
    if problem == "a missing session":
        review_state["session_dir"] = tmp_path / "missing"
    elif problem == "a missing record":
        record.unlink()
    elif problem == "missing event history":
        (session_dir / "events.jsonl").unlink()
    elif problem == "an unsupported record":
        record.write_text(json.dumps({"record_version": 1, "status": "recorded"}), encoding="utf-8")
    elif problem == "an unreadable record":
        record.write_text("{not-json", encoding="utf-8")
    elif problem == "an unrecorded take":
        record.write_text(
            json.dumps({"record_version": 2, "status": "not_started"}), encoding="utf-8"
        )
    elif problem == "a missing processing log":
        review_state["kwargs"]["processing_log"] = str(tmp_path / "missing.log")
    elif problem == "a blank manual action":
        review_state["kwargs"]["manual_actions"] = [{"action_group": "   "}]
    else:
        raise AssertionError(f"unexpected review evidence problem: {problem}")


@when("the reviewer attempts to review the affected session")
def attempt_review_affected_session(loaded: PluginHandle, review_state: dict) -> None:
    review_state["reply"] = loaded.call(
        "review_session", session_dir=str(review_state["session_dir"]), **review_state["kwargs"]
    )


@then(parsers.parse("the review reports {explanation}"))
def review_reports_problem(review_state: dict, explanation: str) -> None:
    expected = {
        "the session does not exist": "does not exist",
        "the record is missing": "human-reference-record.json",
        "the event history is missing": "events.jsonl",
        "the record version is unsupported": "record_version",
        "the record cannot be read": "unreadable",
        "the take has not been recorded": "expected 'recorded'",
        "the processing log does not exist": "processing log does not exist",
        "the manual action needs a description": "action_group",
    }
    assert "cannot review session:" in review_state["reply"]
    assert expected[explanation] in review_state["reply"]


# post-session-review.feature — A tool cannot be supplied without a corresponding manual action


@given("a session location that does not exist", target_fixture="missing_session")
def missing_session(tmp_path: Path) -> Path:
    return tmp_path / "missing"


@when(
    "the reviewer supplies a tool without a manual action in the terminal",
    target_fixture="cli_error",
)
def review_cli_with_unmatched_tool(missing_session: Path) -> int:
    return review.main([str(missing_session), "--tool", "native:buffer"])


@then("the terminal rejects the invalid review request")
def terminal_rejects_invalid_review(cli_error: int) -> None:
    assert cli_error == 2


# post-session-review.feature — A missing session cannot be reviewed from the terminal


@when("the reviewer requests a terminal review of that location", target_fixture="missing_review")
def review_missing_session(missing_session: Path, capsys) -> tuple[int, str]:
    from experiment_plugin import _review_cli

    args = [str(missing_session)]
    assert _review_cli.build_parser().parse_args(args).session_dir == str(missing_session)
    code = review.main(args)
    return code, capsys.readouterr().err


@then("the terminal review reports failure")
def missing_review_fails(missing_review: tuple[int, str]) -> None:
    code, stderr = missing_review
    assert code == 1
    assert "cannot review session:" in stderr


@then("no session evidence is created at that location")
def missing_session_remains_missing(missing_session: Path) -> None:
    assert not missing_session.exists()


# Additional shared or compatibility steps


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


@then("the review CLI exits successfully")
def review_cli_exits_zero(review_state: dict) -> None:
    assert review_state["exit_code"] == 0


@then("the separate output directory contains the reviewed record and human_trajectory.jsonl")
def separate_output_contains_reviewed_files(review_state: dict) -> None:
    out_dir = review_state["output_dir"]
    assert (out_dir / "human-reference-record.reviewed.json").is_file()
    assert (out_dir / "human_trajectory.jsonl").is_file()
