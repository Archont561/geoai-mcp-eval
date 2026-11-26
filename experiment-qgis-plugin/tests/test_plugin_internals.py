"""Unit tests for the host-facing internals of the experiment plugin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment_plugin import plugin, session


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(explicit="/explicit/dir", configured="/from/env")
@given(
    explicit=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-", min_size=1, max_size=30),
    configured=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-", min_size=1, max_size=30),
)
def test_task_dir_prefers_explicit_path_then_environment(
    monkeypatch: pytest.MonkeyPatch, explicit: str, configured: str
) -> None:
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", configured)
    assert plugin._task_dir(explicit) == explicit
    assert plugin._task_dir("") == configured


@example(count=plugin.MAX_EVENTS - 1, source="host:project")
@example(count=plugin.MAX_EVENTS, source="host:project")
@given(
    count=st.integers(min_value=0, max_value=plugin.MAX_EVENTS * 2),
    source=st.text(min_size=1, max_size=30),
)
def test_log_capped_respects_observation_limit(count: int, source: str) -> None:
    mock_session = MagicMock()
    mock_session.tracker.event_count = count
    plugin._log_capped(mock_session, "evt", source, key="value")
    if count < plugin.MAX_EVENTS:
        mock_session.log.assert_called_once_with("evt", source=source, key="value")
    else:
        mock_session.log.assert_not_called()


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(sources=[None, "note", "note"])
@given(
    sources=st.lists(st.one_of(st.none(), st.sampled_from(["note", "host:project"])), max_size=12)
)
def test_session_log_tracks_observation_sources_not_study_tools(
    tmp_path: Path, sources: list[str | None]
) -> None:
    (tmp_path / "t.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: f.geojson\n", encoding="utf-8"
    )
    (tmp_path / "f.geojson").write_text("{}", encoding="utf-8")
    sess = session.start_session("demo-task-001", tmp_path)
    for source in sources:
        sess.log("observed", source=source)
    assert sess.metrics.observation_sources == list(dict.fromkeys(x for x in sources if x))
    assert sess.metrics.raw_event_count == len(sources)
    assert sess.metrics.processing_tools() is None


@given(seconds=st.integers(min_value=-1000, max_value=200_000))
def test_format_elapsed_pads_and_clamps(seconds: int) -> None:
    formatted = plugin._format_elapsed(seconds)
    parts = formatted.split(":")
    assert len(parts) == 3
    hours, minutes, secs = (int(p) for p in parts)
    assert len(parts[1]) == 2 and len(parts[2]) == 2
    assert 0 <= minutes < 60 and 0 <= secs < 60
    clamped = max(0, seconds)
    assert hours * 3600 + minutes * 60 + secs == clamped
