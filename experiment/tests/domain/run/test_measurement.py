"""Unit tests for ``experiment.domain.run.measurement``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run import (
    AssertionResult,
    MeasurementContext,
    OutcomeMetrics,
    TokenUsage,
    TrialKey,
    TrialMeasurement,
)


def test_nullable_tokens_never_imputed() -> None:
    tokens = TokenUsage(calls_missing_usage=2, warnings=["endpoint did not report token usage"])
    assert tokens.input_tokens is None
    assert tokens.output_tokens is None
    assert tokens.total_tokens is None
    assert tokens.calls_missing_usage == 2


def test_trial_measurement_from_assertions_computes_outcomes_and_silent_invalid() -> None:
    key = TrialKey(
        task_id="prep-axis-order-001",
        paradigm="codegen",
        enforcement_level="none",
        repetition=1,
    )
    all_pass = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="exists", predicate="file_exists", tier="trivial", passed=True
            ),
            AssertionResult(
                assertion_id="axis", predicate="point_axis_order", tier="spatial", passed=True
            ),
        ],
    )
    assert all_pass.outcomes == OutcomeMetrics(
        task_success=True, predicate_score=1.0, silent_invalid=False
    )

    silent = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="exists", predicate="file_exists", tier="trivial", passed=True
            ),
            AssertionResult(
                assertion_id="count", predicate="feature_count", tier="trivial", passed=True
            ),
            AssertionResult(
                assertion_id="axis", predicate="point_axis_order", tier="spatial", passed=False
            ),
        ],
    )
    assert silent.outcomes.task_success is False
    assert silent.outcomes.predicate_score == pytest.approx(2 / 3)
    assert silent.outcomes.silent_invalid is True

    crashed = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="exists", predicate="file_exists", tier="trivial", passed=False
            ),
            AssertionResult(
                assertion_id="axis", predicate="point_axis_order", tier="spatial", passed=False
            ),
        ],
    )
    assert crashed.outcomes.task_success is False
    assert crashed.outcomes.predicate_score == 0.0
    assert crashed.outcomes.silent_invalid is False

    empty = TrialMeasurement.from_assertions(key=key, assertions=[])
    assert empty.outcomes == OutcomeMetrics(
        task_success=False, predicate_score=0.0, silent_invalid=False
    )


def test_measurement_context_pydantic_validation() -> None:
    ctx = MeasurementContext(deliverable_readable=True)
    assert MeasurementContext.model_validate_json(ctx.model_dump_json()) == ctx
    with pytest.raises(ValidationError):
        MeasurementContext(extra_key="bad")  # type: ignore[call-arg]


@given(
    passes=st.lists(st.booleans(), min_size=1, max_size=12),
    tiers=st.lists(st.sampled_from(["trivial", "spatial", "value"]), min_size=1, max_size=12),
)
def test_outcome_metrics_properties(passes: list[bool], tiers: list[str]) -> None:
    n = min(len(passes), len(tiers))
    assertions = [
        AssertionResult(
            assertion_id=f"a-{idx}",
            predicate=f"pred_{idx}",
            tier=tiers[idx],  # type: ignore[arg-type]
            passed=passes[idx],
        )
        for idx in range(n)
    ]
    key = TrialKey(task_id="t", paradigm="codegen", enforcement_level="none", repetition=1)
    measurement = TrialMeasurement.from_assertions(key=key, assertions=assertions)
    assert measurement.outcomes.task_success is all(passes[:n])
    assert 0.0 <= measurement.outcomes.predicate_score <= 1.0
    if measurement.outcomes.task_success:
        assert measurement.outcomes.predicate_score == 1.0
        assert measurement.outcomes.silent_invalid is False
