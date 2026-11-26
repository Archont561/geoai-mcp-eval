"""Unit tests for ``experiment.domain.run.metrics``."""

from __future__ import annotations

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run.metrics import _TranscriptTally, extract_transcript_metrics


@example(tool_count=2, violations=1, input_tokens=120, output_tokens=40, llm_calls=2)
@given(
    tool_count=st.integers(min_value=0, max_value=10),
    violations=st.integers(min_value=0, max_value=10),
    input_tokens=st.integers(min_value=0, max_value=10000),
    output_tokens=st.integers(min_value=0, max_value=10000),
    llm_calls=st.integers(min_value=0, max_value=100),
)
def test_extract_transcript_metrics_counts_calls_repairs_and_violations(
    tool_count: int, violations: int, input_tokens: int, output_tokens: int, llm_calls: int
) -> None:
    entries = [
        {"role": "meta", "task": "analysis-de9im-001"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": str(i), "function": {"name": "feature_info", "arguments": "{}"}}
                for i in range(tool_count)
            ],
        },
    ]
    for _ in range(violations):
        entries.extend(
            [
                {"role": "tool", "error_code": "INVALID_SCHEMA"},
                {"role": "assistant", "content": "corrected"},
            ]
        )
    entries.append(
        {
            "role": "harness",
            "event": "usage_summary",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "llm_calls": llm_calls,
            },
        }
    )
    metrics = extract_transcript_metrics(entries, wall_seconds=3.25)
    assert metrics.wall_seconds == 3.25
    assert metrics.llm_calls == llm_calls
    assert metrics.tool_calls == tool_count
    assert metrics.schema_violations == violations
    assert metrics.repair_turns == violations
    assert metrics.tokens.total_tokens == input_tokens + output_tokens

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
