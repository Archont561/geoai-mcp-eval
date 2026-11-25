"""Unit tests for ``experiment_plugin._session_io``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from experiment_plugin import _session_io


def test_template_skeleton_and_allocate_session_dir(tmp_path: Path) -> None:
    skel = _session_io.template_skeleton()
    assert skel["record_version"] == 2
    ts = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    d1 = _session_io.allocate_session_dir(tmp_path, ts)
    d2 = _session_io.allocate_session_dir(tmp_path, ts)
    assert d1.is_dir() and d2.is_dir() and d1 != d2
    rendered = _session_io.render_session_log(
        task_id="demo-task-001",
        output_dir=d1,
        started_at=ts,
        status="active",
        events_path=d1 / "events.jsonl",
    )
    assert "demo-task-001" in rendered and "events.jsonl" in rendered
