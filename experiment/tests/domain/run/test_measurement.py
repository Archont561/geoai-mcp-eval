"""Unit tests for ``experiment.domain.run.measurement``."""

from __future__ import annotations

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run import (
    AssertionResult,
    MeasurementContext,
    TokenUsage,
    TrialKey,
    TrialMeasurement,
)


@example(missing=2, warning="endpoint did not report token usage")
@given(missing=st.integers(min_value=0, max_value=100), warning=st.text(max_size=80))
def test_nullable_tokens_never_imputed(missing: int, warning: str) -> None:
    tokens = TokenUsage(calls_missing_usage=missing, warnings=[warning])
    assert tokens.input_tokens is None
    assert tokens.output_tokens is None
    assert tokens.total_tokens is None
    assert tokens.calls_missing_usage == missing
    assert tokens.warnings == [warning]


@given(
    readable=st.one_of(st.none(), st.booleans()),
    extra=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=15),
)
def test_measurement_context_pydantic_validation(readable: bool | None, extra: str) -> None:
    ctx = MeasurementContext(deliverable_readable=readable)
    assert MeasurementContext.model_validate_json(ctx.model_dump_json()) == ctx
    with pytest.raises(ValidationError):
        MeasurementContext.model_validate(
            {"deliverable_readable": readable, f"extra_{extra}": "bad"}
        )


@example(results=[(True, "trivial"), (True, "spatial")], readable=None)
@example(results=[(True, "trivial"), (True, "trivial"), (False, "spatial")], readable=None)
@example(results=[(False, "trivial"), (False, "spatial")], readable=None)
@example(results=[], readable=None)
@given(
    results=st.lists(
        st.tuples(st.booleans(), st.sampled_from(["trivial", "spatial", "value"])), max_size=12
    ),
    readable=st.one_of(st.none(), st.booleans()),
)
def test_outcome_metrics_properties(results: list[tuple[bool, str]], readable: bool | None) -> None:
    assertions = [
        AssertionResult(
            assertion_id=f"a-{idx}",
            predicate=f"pred_{idx}",
            tier=tier,  # type: ignore[arg-type]
            passed=passed,
        )
        for idx, (passed, tier) in enumerate(results)
    ]
    key = TrialKey(task_id="t", paradigm="codegen", enforcement_level="none", repetition=1)
    measurement = TrialMeasurement.build(
        key=key, assertions=assertions, context=MeasurementContext(deliverable_readable=readable)
    )
    trivial = [passed for passed, tier in results if tier == "trivial"]
    domain_failure = any(not passed for passed, tier in results if tier != "trivial")
    deliverable_ok = all(trivial) and readable is not False if trivial else readable is True
    assert measurement.outcomes.task_success is (bool(results) and all(p for p, _ in results))
    assert measurement.outcomes.predicate_score == pytest.approx(
        sum(p for p, _ in results) / len(results) if results else 0.0
    )
    assert measurement.outcomes.silent_invalid is (deliverable_ok and domain_failure)
