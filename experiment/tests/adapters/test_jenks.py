"""Unit and property tests for ``experiment.adapters.jenks`` (``jenkspy``)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from experiment.adapters.jenks import fisher_jenks_breaks


@given(
    values=st.lists(
        st.integers(min_value=-500, max_value=500).map(float),
        min_size=2,
        max_size=20,
        unique=True,
    ),
    data=st.data(),
)
def test_fisher_jenks_breaks_sorted_subset_with_max_endpoint(
    values: list[float], data: st.DataObject
) -> None:
    k = data.draw(st.integers(min_value=1, max_value=len(values)))
    breaks = fisher_jenks_breaks(values, k)
    assert len(breaks) == k
    assert breaks == sorted(breaks)
    assert breaks[-1] == max(values)
    assert set(breaks).issubset(set(values))


@given(offset=st.integers(min_value=-1000, max_value=1000))
def test_fisher_jenks_separates_translated_clusters(offset: int) -> None:
    values = [float(value + offset) for value in [1, 2, 3, 100, 101, 102, 500, 501]]
    assert fisher_jenks_breaks(values, 3) == [3 + offset, 102 + offset, 501 + offset]
    assert fisher_jenks_breaks(values, 1) == [501 + offset]


@given(value=st.integers(-1000, 1000), count=st.integers(max_value=0))
def test_fisher_jenks_rejects_invalid_inputs(value: int, count: int) -> None:
    with pytest.raises(ValueError, match="at least one"):
        fisher_jenks_breaks([], 2)
    with pytest.raises(ValueError, match="class_count"):
        fisher_jenks_breaks([float(value)], count)
    with pytest.raises(ValueError, match="class_count"):
        fisher_jenks_breaks([float(value)] * 3, 2)
