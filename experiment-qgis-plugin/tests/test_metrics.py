"""Unit tests for ``experiment_plugin.metrics``."""

from __future__ import annotations

from experiment_plugin import metrics


def test_metrics_helpers_and_state() -> None:
    assert metrics.ordered_unique(["a", "b", "a"]) == ["a", "b"]
    sanitized = metrics.sanitize_parameters({"DISTANCE": 5, "RAW": object()})
    assert sanitized["DISTANCE"] == 5
    assert isinstance(sanitized["RAW"], str)

    state = metrics.SessionMetricsState()
    state.note_observation_source("note")
    state.note_observation_source("note")
    assert state.observation_sources == ["note"]
    assert state.processing_tools() is None
