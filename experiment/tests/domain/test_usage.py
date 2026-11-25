"""Unit tests for ``experiment.domain.usage``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.usage import (
    UsageAccumulator,
    UsageSnapshot,
    aggregate_run_usage,
    extract_response_usage,
)

TOKEN_COUNT = st.integers(min_value=0, max_value=50_000)


@given(prompt_tokens=TOKEN_COUNT, completion_tokens=TOKEN_COUNT)
def test_extract_response_usage_supports_openai_and_input_output_keys(
    prompt_tokens: int, completion_tokens: int
) -> None:
    total = prompt_tokens + completion_tokens
    openai_snap = extract_response_usage(
        {
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
            }
        }
    )
    assert openai_snap == UsageSnapshot(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=total,
        warning=None,
    )
    alt_snap = extract_response_usage(
        {"usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens}}
    )
    assert alt_snap == openai_snap


def test_extract_response_usage_never_estimates_missing_or_invalid_values() -> None:
    missing = extract_response_usage({"choices": [{"message": {"content": "hello"}}]})
    assert missing.input_tokens is None
    assert missing.output_tokens is None
    assert missing.total_tokens is None
    assert missing.warning is not None

    partial = extract_response_usage({"usage": {"prompt_tokens": 50, "completion_tokens": None}})
    assert partial.input_tokens == 50
    assert partial.output_tokens is None
    assert partial.total_tokens is None
    assert partial.warning is not None

    bad_bool = extract_response_usage({"usage": {"prompt_tokens": True, "completion_tokens": -3}})
    assert bad_bool.input_tokens is None
    assert bad_bool.output_tokens is None
    assert bad_bool.total_tokens is None
    assert bad_bool.warning is not None


@given(
    turns=st.lists(st.tuples(TOKEN_COUNT, TOKEN_COUNT), min_size=1, max_size=10),
    cap=st.integers(min_value=1, max_value=500_000),
)
def test_usage_accumulator_sums_turns_and_detects_cap_accurately(
    turns: list[tuple[int, int]], cap: int
) -> None:
    acc = UsageAccumulator(max_cell_tokens=cap)
    for inp, out in turns:
        acc.record(UsageSnapshot(input_tokens=inp, output_tokens=out, total_tokens=inp + out))
    expected_in = sum(inp for inp, _ in turns)
    expected_out = sum(out for _, out in turns)
    expected_total = expected_in + expected_out
    summary = acc.to_summary()
    assert summary["input_tokens"] == expected_in
    assert summary["output_tokens"] == expected_out
    assert summary["total_tokens"] == expected_total
    assert summary["calls_with_usage"] == len(turns)
    assert summary["calls_missing_usage"] == 0
    assert acc.cap_exceeded is (expected_total > cap)


def test_usage_accumulator_flags_partial_missing_and_aggregates_nulls() -> None:
    acc = UsageAccumulator(max_cell_tokens=500)
    acc.record(UsageSnapshot(input_tokens=100, output_tokens=40, total_tokens=140))
    summary = acc.to_summary()
    acc.record(
        UsageSnapshot(
            input_tokens=None, output_tokens=None, total_tokens=None, warning="missing usage"
        )
    )
    partial = acc.to_summary()
    assert partial["input_tokens"] is None
    assert partial["output_tokens"] is None
    assert partial["total_tokens"] is None
    assert partial["calls_missing_usage"] == 1
    assert partial["warnings"] == ["missing usage"]

    agg = aggregate_run_usage([summary, partial])
    assert agg["total_tokens"] is None
    assert agg["cells_missing_usage"] == 1


def test_usage_accumulator_to_token_usage_preserves_nulls() -> None:
    acc = UsageAccumulator(max_cell_tokens=500)
    snapshot = UsageSnapshot(input_tokens=10, output_tokens=None, total_tokens=None, warning="part")
    acc.record(snapshot)
    dto = acc.to_token_usage()
    assert dto.input_tokens == 10
    assert dto.output_tokens is None
    assert dto.total_tokens is None
    assert dto.calls_missing_usage == 1
    assert dto.max_trial_tokens == 500
    assert dto.warnings == ["part"]


@given(neg=st.integers(max_value=-1))
def test_usage_models_reject_negative_tokens_and_non_positive_cap(neg: int) -> None:
    with pytest.raises(ValidationError):
        UsageSnapshot(input_tokens=neg, output_tokens=0, total_tokens=0)
    with pytest.raises(ValidationError):
        UsageAccumulator(max_cell_tokens=neg if neg < 0 else 0)
