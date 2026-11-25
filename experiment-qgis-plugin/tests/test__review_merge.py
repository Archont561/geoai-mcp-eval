"""Unit tests for ``experiment_plugin._review_merge``."""

from __future__ import annotations

from experiment_plugin import _review_merge


def test_normalize_manual_inputs_and_dedup_key() -> None:
    groups = _review_merge.normalize_manual_inputs(
        [_review_merge.ReviewActionInput(action_group="digitize", tool="pencil")],
        "2026-11-24T12:00:00Z",
    )
    assert len(groups) == 1
    assert groups[0].action_group == "digitize"
    assert groups[0].tool == "pencil"
