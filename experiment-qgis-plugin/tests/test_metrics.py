"""Unit tests for ``experiment_plugin.metrics``."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from experiment_plugin import metrics


@given(items=st.lists(st.text(min_size=1, max_size=10), max_size=20))
def test_ordered_unique_preserves_first_seen_order_without_duplicates(items: list[str]) -> None:
    unique = metrics.ordered_unique(items)
    assert len(unique) == len(set(items))
    assert set(unique) == set(items)
    positions = [items.index(val) for val in unique]
    assert positions == sorted(positions)


@given(sources=st.lists(st.text(min_size=1, max_size=12), max_size=15))
def test_session_metrics_state_deduplicates_observation_sources(sources: list[str]) -> None:
    state = metrics.SessionMetricsState()
    for src in sources:
        state.note_observation_source(src)
    assert state.observation_sources == metrics.ordered_unique(sources)
    assert state.processing_tools() is None


def test_metrics_sanitize_parameters() -> None:
    sanitized = metrics.sanitize_parameters({"DISTANCE": 5, "RAW": object()})
    assert sanitized is not None
    assert sanitized["DISTANCE"] == 5
    assert isinstance(sanitized["RAW"], str)
