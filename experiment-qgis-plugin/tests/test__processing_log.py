"""Unit tests for ``experiment_plugin._processing_log``."""

from __future__ import annotations

from pathlib import Path

from experiment_plugin import _processing_log


def test_parse_processing_log_file_handles_empty_and_qgis_calls(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.write_text("\n", encoding="utf-8")
    entries, warnings = _processing_log.parse_processing_log_file(empty)
    assert entries == [] and warnings == []

    log = tmp_path / "proc.log"
    log.write_text(
        "ALGORITHM|2026-11-24 10:00:00|processing.run(\"native:buffer\", {'DISTANCE': 10})\n",
        encoding="utf-8",
    )
    parsed, parse_warnings = _processing_log.parse_processing_log_file(log)
    assert parse_warnings == []
    assert len(parsed) == 1
    assert parsed[0].algorithm_id == "native:buffer"
    assert parsed[0].parameters["DISTANCE"] == 10
