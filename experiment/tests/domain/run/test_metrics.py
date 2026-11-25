"""Unit tests for ``experiment.domain.run.metrics``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run.metrics import _TranscriptTally, extract_transcript_metrics


def test_extract_transcript_metrics_counts_calls_repairs_and_violations() -> None:
    entries = [
        {"role": "meta", "task": "analysis-de9im-001"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "filter_features", "arguments": "{}"}},
                {"id": "2", "function": {"name": "relate_de9im", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_name": "filter_features", "error_code": "INVALID_SCHEMA"},
        {"role": "assistant", "content": '{"relation": "touches", "de9im": "FF2F11212"}'},
        {
            "role": "harness",
            "event": "usage_summary",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 40,
                "total_tokens": 160,
                "llm_calls": 2,
                "calls_with_usage": 2,
                "calls_missing_usage": 0,
                "max_cell_tokens": None,
                "cap_exceeded": False,
                "warnings": [],
            },
        },
    ]
    metrics = extract_transcript_metrics(entries, wall_seconds=3.25)
    assert metrics.wall_seconds == 3.25
    assert metrics.llm_calls == 2
    assert metrics.tool_calls == 2
    assert metrics.schema_violations == 1
    assert metrics.repair_turns == 1
    assert metrics.tokens.total_tokens == 160

    empty = extract_transcript_metrics([])
    assert empty.llm_calls == 0
    assert empty.tool_calls == 0
    assert empty.repair_turns == 0
    assert empty.schema_violations == 0
    assert empty.tokens.total_tokens is None


@given(
    tool_counts=st.lists(st.integers(min_value=0, max_value=4), max_size=8),
    wall_s=st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False),
)
def test_extract_transcript_metrics_counts_arbitrary_assistant_turns_and_tool_calls(
    tool_counts: list[int], wall_s: float
) -> None:
    entries = [
        {
            "role": "assistant",
            "content": "step",
            "tool_calls": [
                {"id": str(i), "function": {"name": f"op_{i}", "arguments": "{}"}}
                for i in range(n_tools)
            ],
        }
        for n_tools in tool_counts
    ]
    metrics = extract_transcript_metrics(entries, wall_seconds=wall_s)
    assert metrics.llm_calls == len(tool_counts)
    assert metrics.tool_calls == sum(tool_counts)
    assert metrics.wall_seconds == wall_s


@given(
    turns=st.integers(min_value=0, max_value=50),
    calls=st.integers(min_value=0, max_value=100),
    violations=st.integers(min_value=0, max_value=50),
    repairs=st.integers(min_value=0, max_value=50),
)
def test_transcript_tally_roundtrips_non_negative_counts(
    turns: int, calls: int, violations: int, repairs: int
) -> None:
    tally = _TranscriptTally(
        assistant_turns=turns,
        tool_calls=calls,
        schema_violations=violations,
        repair_turns=repairs,
    )
    assert _TranscriptTally.model_validate_json(tally.model_dump_json()) == tally


@given(neg=st.integers(max_value=-1))
def test_transcript_tally_rejects_negative_counts(neg: int) -> None:
    with pytest.raises(ValidationError):
        _TranscriptTally(
            assistant_turns=neg,
            tool_calls=0,
            schema_violations=0,
            repair_turns=0,
        )
