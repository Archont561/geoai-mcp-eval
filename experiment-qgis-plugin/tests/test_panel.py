"""Properties of the participant-facing session panel."""

from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st

from experiment_plugin import panel


@example(seconds=0)
@example(seconds=65)
@example(seconds=3600 * 26 + 61)
@example(seconds=-5)
@given(seconds=st.floats(min_value=-1_000_000, max_value=10_000_000, allow_nan=False))
def test_elapsed_clock_represents_nonnegative_whole_seconds(seconds: float) -> None:
    hours, minutes, secs = map(int, panel.format_elapsed(seconds).split(":"))
    assert 0 <= minutes < 60
    assert 0 <= secs < 60
    assert hours * 3600 + minutes * 60 + secs == max(0, int(seconds))


@given(message=st.text())
def test_exception_detail_preserves_error_message(message: str) -> None:
    assert panel.exception_detail(RuntimeError(message)) == message
