"""Properties of host observation lifecycle boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from plugin_harness import FakeSignal

from experiment_plugin import host_observation


@example(actions=["pause", "resume", "close", "close"])
@given(actions=st.lists(st.sampled_from(["pause", "resume", "close", "fire"]), max_size=40))
def test_observers_follow_pause_resume_and_close_boundaries(actions: list[str]) -> None:
    hooks = host_observation.HostHooks()
    signal = FakeSignal()
    owner = SimpleNamespace(signal=signal)
    observed: list[int] = []
    hooks.connect(owner, "signal", lambda value: observed.append(value))
    enabled, closed = True, False
    expected = []
    for index, action in enumerate(actions):
        if action == "fire":
            signal.fire(index)
            if enabled and not closed:
                expected.append(index)
        elif action == "pause":
            hooks.pause()
            enabled = False
        elif action == "resume":
            hooks.resume()
            enabled = not closed
        else:
            hooks.close()
            closed, enabled = True, False
        assert observed == expected
    hooks.close()
    hooks.close()
    assert not signal.slots
    with pytest.raises(RuntimeError, match="closed"):
        hooks.connect(owner, "signal", lambda: None)
