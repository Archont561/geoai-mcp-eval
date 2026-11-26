"""Properties of session storage and human-readable logs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment_plugin import _session_io


@example(task_id="demo-task-001", second=0)
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    task_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=30),
    second=st.integers(min_value=0, max_value=59),
)
def test_same_time_sessions_have_unique_directories_and_readable_logs(
    tmp_path: Path, task_id: str, second: int
) -> None:
    assert _session_io.template_skeleton()["record_version"] == 2
    started = datetime(2026, 11, 24, 12, 0, second, tzinfo=UTC)
    first = _session_io.allocate_session_dir(tmp_path, started)
    second_dir = _session_io.allocate_session_dir(tmp_path, started)
    assert first.is_dir() and second_dir.is_dir() and first != second_dir
    rendered = _session_io.render_session_log(
        task_id=task_id,
        output_dir=first,
        started_at=started,
        status="active",
        events_path=first / "events.jsonl",
    )
    assert task_id in rendered and "events.jsonl" in rendered
