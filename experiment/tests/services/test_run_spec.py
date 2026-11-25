"""Unit tests for ``experiment.services.run_spec``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.run_spec import RunSpecError, RunSpecInput, parse_enforce, parse_run_spec


@given(
    arm=st.sampled_from(["A", "B", "both"]),
    repetitions=st.integers(min_value=1, max_value=20),
    enforce=st.sampled_from(["N0", "N1", "N2", "N3", "N4", "none", "syntactic", "semantic_repair"]),
)
def test_parse_run_spec_expands_arms_and_repetitions(
    arm: str, repetitions: int, enforce: str
) -> None:
    spec = parse_run_spec(
        RunSpecInput(
            driver="scripted",
            arm=arm,
            task="all",
            backend="local",
            repetitions=repetitions,
            enforce=enforce,
        )
    )
    expected_arms = ("A", "B") if arm == "both" else (arm,)
    assert spec.arms == expected_arms
    assert spec.repetitions == repetitions
    assert spec.enforce == parse_enforce(enforce)


@given(bad_reps=st.integers(max_value=0))
def test_parse_run_spec_rejects_non_positive_repetitions(bad_reps: int) -> None:
    with pytest.raises(RunSpecError, match="positive integer"):
        parse_run_spec(RunSpecInput(driver="scripted", repetitions=bad_reps))


def test_parse_run_spec_and_enforce_error_paths() -> None:
    assert parse_enforce("N2") == "syntactic"
    assert parse_enforce("semantic_repair") == "semantic_repair"
    with pytest.raises(RunSpecError):
        parse_enforce("N9")
    with pytest.raises(RunSpecError, match="driver"):
        parse_run_spec(RunSpecInput(driver="bogus"))
    with pytest.raises(ValidationError):
        RunSpecInput(driver="scripted", bogus=1)  # type: ignore[call-arg]
