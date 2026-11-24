"""Focused unit tests for non-destructive post-session review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from experiment_plugin import review, session

TASK_ROOT = Path(__file__).resolve().parents[2] / "experiment" / "tasks"
UTF8 = "utf-8"


def copy_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "tasks"
    suite.mkdir(parents=True)
    yaml_src = TASK_ROOT / "prep-axis-order-001.yaml"
    shutil.copy2(yaml_src, suite / yaml_src.name)
    fixture_src = session.task_fixture(yaml_src)
    fixture_rel = fixture_src.relative_to(TASK_ROOT)
    (suite / fixture_rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_src, suite / fixture_rel)
    return suite


def make_recorded_take(
    tmp_path: Path,
    *,
    processing_connected: bool = True,
    with_execution: bool = True,
) -> Path:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    hooks = ["project", "processing"] if processing_connected else ["project"]
    recorder.set_hook_status(hooks, [], processing_connected=processing_connected)
    if with_execution:
        recorder.record_processing_execution(
            "native:reprojectlayer",
            parameters={"TARGET_CRS": "EPSG:2180"},
            entry_timestamp="2026-11-24T12:00:05+00:00",
        )
    recorder.finish()
    return recorder.output_dir


def test_parse_processing_log_handles_qgis_expressions_and_legacy_pipe(tmp_path: Path) -> None:
    log_path = tmp_path / "processing.log"
    log_path.write_text(
        "\n".join(
            [
                "INFO|2026-11-24 12:00:00|Started",
                (
                    "ALGORITHM|2026-11-24 12:01:02|processing.run("
                    '"native:reprojectlayer", '
                    "{'INPUT': 'in.geojson', "
                    "'TARGET_CRS': QgsCoordinateReferenceSystem('EPSG:2180')})"
                ),
                "ALGORITHM|2026-11-24 12:02:10|gdal:warpreproject|{'RESAMPLING': 0}",
                "ALGORITHM|2026-11-24 12:03:00|not-valid-syntax(((",
            ]
        )
        + "\n",
        encoding=UTF8,
    )
    executions, errors = review.parse_processing_log(log_path)
    assert len(executions) == 2
    assert executions[0].algorithm_id == "native:reprojectlayer"
    assert executions[0].parameters == {
        "INPUT": "in.geojson",
        "TARGET_CRS": "QgsCoordinateReferenceSystem('EPSG:2180')",
    }
    assert executions[1].algorithm_id == "gdal:warpreproject"
    assert executions[1].parameters == {"RESAMPLING": 0}
    assert len(errors) == 1


def test_parse_processing_log_empty_file_is_valid_zero_algorithms(tmp_path: Path) -> None:
    log_path = tmp_path / "processing.log"
    log_path.write_text("INFO|2026-11-24 12:00:00|No algorithms executed\n", encoding=UTF8)
    executions, errors = review.parse_processing_log(log_path)
    assert executions == []
    assert errors == []


def test_review_pure_manual_with_empty_processing_log_verifies_empty_tools(tmp_path: Path) -> None:
    take = make_recorded_take(tmp_path, processing_connected=False, with_execution=False)
    empty_log = tmp_path / "processing.log"
    empty_log.write_text("", encoding=UTF8)

    result = review.review_session(
        take,
        manual_actions=[review.ReviewActionInput(action_group="digitized boundary manually")],
        processing_log=empty_log,
        mark_reviewed=True,
    )
    assert result.record["session"]["metrics_status"] == "reviewed"
    assert result.record["session"]["steps"] == 1
    assert result.record["session"]["tools"] == []
    assert len(result.trajectory_entries) == 1
    assert result.trajectory_entries[0]["kind"] == "manual_action_group"
    assert result.trajectory_entries[0]["tool"] is None


def test_review_incomplete_processing_log_keeps_metrics_pending(tmp_path: Path) -> None:
    take = make_recorded_take(tmp_path, processing_connected=False, with_execution=False)
    bad_log = tmp_path / "processing.log"
    bad_log.write_text("ALGORITHM|2026-11-24 12:03:00|corrupt-payload\n", encoding=UTF8)

    result = review.review_session(take, processing_log=bad_log, mark_reviewed=True)
    assert result.record["session"]["metrics_status"] == "pending_review"
    assert "processing_history_incomplete" in result.record["study_metrics"]["pending_reasons"]
    assert result.record["session"]["steps"] is None
    assert result.record["session"]["tools"] is None


def test_review_deduplicates_matching_processing_log_entry_and_is_idempotent(
    tmp_path: Path,
) -> None:
    take = make_recorded_take(tmp_path, processing_connected=True, with_execution=True)
    log_path = tmp_path / "processing.log"
    log_path.write_text(
        'ALGORITHM|2026-11-24T12:00:05+00:00|processing.run("native:reprojectlayer", '
        "{'TARGET_CRS': 'EPSG:2180'})\n",
        encoding=UTF8,
    )
    first = review.review_session(
        take,
        manual_actions=[{"action_group": "saved output", "tool": "qgis:save-features-as"}],
        processing_log=log_path,
        mark_reviewed=True,
    )
    second = review.review_session(
        take,
        manual_actions=[{"action_group": "saved output", "tool": "qgis:save-features-as"}],
        processing_log=log_path,
        mark_reviewed=True,
    )
    assert first.record["session"]["steps"] == 2
    assert second.record["session"]["steps"] == 2
    assert len(second.trajectory_entries) == 2


def test_review_rejects_invalid_sessions_and_inputs(tmp_path: Path) -> None:
    with pytest.raises(review.ReviewError, match="does not exist"):
        review.review_session(tmp_path / "missing")

    empty_dir = tmp_path / "empty-session"
    empty_dir.mkdir()
    with pytest.raises(review.ReviewError, match="human-reference-record.json"):
        review.review_session(empty_dir)

    take = make_recorded_take(tmp_path)
    (take / "events.jsonl").unlink()
    with pytest.raises(review.ReviewError, match="events.jsonl"):
        review.review_session(take)

    bad_version = tmp_path / "v1"
    bad_version.mkdir()
    (bad_version / "events.jsonl").write_text("", encoding=UTF8)
    (bad_version / "human-reference-record.json").write_text(
        json.dumps({"record_version": 1, "status": "recorded"}), encoding=UTF8
    )
    with pytest.raises(review.ReviewError, match="record_version"):
        review.review_session(bad_version)

    take2 = make_recorded_take(tmp_path / "t2")
    with pytest.raises(ValueError, match="action_group"):
        review.review_session(take2, manual_actions=[{"action_group": "   "}])


def test_review_cli_returns_nonzero_on_errors(tmp_path: Path, capsys) -> None:
    code = review.main([str(tmp_path / "missing")])
    assert code == 1
    assert "cannot review session:" in capsys.readouterr().err

    code_mismatch = review.main([str(tmp_path), "--tool", "native:buffer"])
    assert code_mismatch == 2


def test_review_preserves_session_logged_manual_actions_and_handles_corrupt_inputs(
    tmp_path: Path,
) -> None:
    suite = copy_suite(tmp_path / "keep")
    recorder = session.start_session("prep-axis-order-001", suite)
    recorder.set_hook_status(["project", "processing"], [], processing_connected=True)
    recorder.record_manual_action_group("styled layer", tool=None)
    recorder.finish()

    result = review.review_session(
        recorder.output_dir,
        manual_actions=[{"action_group": "exported GeoJSON", "tool": "qgis:save-features-as"}],
        mark_reviewed=True,
    )
    assert result.record["session"]["steps"] == 2
    assert result.record["session"]["tools"] == ["qgis:save-features-as"]
    assert [entry["origin"] for entry in result.trajectory_entries] == [
        "session_manual",
        "post_session_review",
    ]

    with pytest.raises(review.ReviewError, match="processing log does not exist"):
        review.review_session(recorder.output_dir, processing_log=tmp_path / "missing.log")

    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "events.jsonl").write_text("", encoding=UTF8)
    (corrupt / "human-reference-record.json").write_text("{not-json", encoding=UTF8)
    with pytest.raises(review.ReviewError, match="unreadable"):
        review.review_session(corrupt)

    wrong_status = tmp_path / "wrong-status"
    wrong_status.mkdir()
    (wrong_status / "events.jsonl").write_text("", encoding=UTF8)
    (wrong_status / "human-reference-record.json").write_text(
        json.dumps({"record_version": 2, "status": "not_started"}), encoding=UTF8
    )
    with pytest.raises(review.ReviewError, match="expected 'recorded'"):
        review.review_session(wrong_status)


def test_review_atomic_write_cleans_up_temp_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    take = make_recorded_take(tmp_path)

    def boom(_src: Path, _dst: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        review.review_session(take, mark_reviewed=True)
    assert not list(take.glob(".human-reference-record-reviewed-*.tmp"))
    assert not (take / review.REVIEWED_RECORD_FILENAME).exists()
