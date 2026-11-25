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


def test_fisher_jenks_breaks_known_clusters_and_validation() -> None:
    values = [1.0, 2.0, 3.0, 100.0, 101.0, 102.0, 500.0, 501.0]
    assert fisher_jenks_breaks(values, 3) == [3.0, 102.0, 501.0]
    assert fisher_jenks_breaks(values, 1) == [501.0]
    with pytest.raises(ValueError, match="at least one"):
        fisher_jenks_breaks([], 2)
    with pytest.raises(ValueError, match="class_count"):
        fisher_jenks_breaks(values, 0)
    with pytest.raises(ValueError, match="class_count"):
        fisher_jenks_breaks([1.0, 1.0, 1.0], 2)
