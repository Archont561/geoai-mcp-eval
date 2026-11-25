"""Unit tests for ``experiment_plugin._state``."""

from __future__ import annotations

from experiment_plugin import _state


def test_state_exports_expected_constants() -> None:
    assert _state.DEFAULT_TASK_ID
    assert "session" in _state.ACTIVE
    assert "session" in _state.LAST
