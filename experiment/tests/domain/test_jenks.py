"""Unit and property tests for ``experiment.domain.jenks``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from experiment.domain.jenks import validate_jenks_inputs


@given(
    values=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=25,
    )
)
def test_validate_jenks_inputs_returns_sorted_floats_and_enforces_bounds(
    values: list[float],
) -> None:
    unique_count = len(set(values))
    result = validate_jenks_inputs(values, unique_count)
    assert result == sorted(float(v) for v in values)
    with pytest.raises(ValueError, match="class_count"):
        validate_jenks_inputs(values, unique_count + 1)
    with pytest.raises(ValueError, match="class_count"):
        validate_jenks_inputs(values, 0)


@given(class_count=st.integers())
def test_validate_jenks_inputs_rejects_empty(class_count: int) -> None:
    with pytest.raises(ValueError, match="at least one"):
        validate_jenks_inputs([], class_count)
