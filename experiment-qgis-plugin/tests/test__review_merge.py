"""Properties of post-session review normalization."""

from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st

from experiment_plugin import _review_merge


@example(group="digitize", tool="pencil")
@given(
    group=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=30).filter(
        str.strip
    ),
    tool=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=30).filter(str.strip),
)
def test_manual_inputs_preserve_normalized_group_and_tool(group: str, tool: str) -> None:
    timestamp = "2026-11-24T12:00:00Z"
    groups = _review_merge.normalize_manual_inputs(
        [_review_merge.ReviewActionInput(action_group=group, tool=tool)], timestamp
    )
    assert len(groups) == 1
    assert groups[0].action_group == group.strip()
    assert groups[0].tool == tool.strip()
    assert groups[0].ts == timestamp
