"""Unit tests for ``experiment.domain.usage``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.usage import (
    UsageAccumulator,
    UsageSnapshot,
    aggregate_run_usage,
    extract_response_usage,
)


def test_extract_response_usage_supports_openai_and_input_output_keys() -> None:
    openai_snap = extract_response_usage(
        {"usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165}}
    )
    assert openai_snap == UsageSnapshot(
        input_tokens=120, output_tokens=45, total_tokens=165, warning=None
    )

    alt_snap = extract_response_usage({"usage": {"input_tokens": 80, "output_tokens": 20}})
    assert alt_snap == UsageSnapshot(
        input_tokens=80, output_tokens=20, total_tokens=100, warning=None
    )


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


def test_usage_accumulator_sums_multi_turn_calls_and_flags_partial_missing() -> None:
    acc = UsageAccumulator(max_cell_tokens=500)
    acc.record(UsageSnapshot(input_tokens=100, output_tokens=40, total_tokens=140))
    acc.record(UsageSnapshot(input_tokens=150, output_tokens=60, total_tokens=210))
    assert not acc.cap_exceeded
    summary = acc.to_summary()
    assert summary["input_tokens"] == 250
    assert summary["output_tokens"] == 100
    assert summary["total_tokens"] == 350
    assert summary["calls_with_usage"] == 2
    assert summary["calls_missing_usage"] == 0
    assert summary["warnings"] == []

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


def test_usage_models_pydantic_validation() -> None:
    snap = UsageSnapshot(input_tokens=10, output_tokens=5, total_tokens=15)
    assert UsageSnapshot.model_validate_json(snap.model_dump_json()) == snap
    with pytest.raises(ValidationError):
        UsageSnapshot(input_tokens=-1, output_tokens=0, total_tokens=0)
    with pytest.raises(ValidationError):
        UsageAccumulator(max_cell_tokens=0)
