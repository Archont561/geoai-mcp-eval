"""Unit tests for ``experiment.domain.jenks``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.jenks import _SplitSearch, fisher_jenks_breaks


def test_fisher_jenks_known_fixture_and_invalid_inputs() -> None:
    values = [1.0, 2.0, 3.0, 100.0, 101.0, 102.0, 500.0, 501.0]
    assert fisher_jenks_breaks(values, 3) == [3.0, 102.0, 501.0]
    assert fisher_jenks_breaks(values, 1) == [501.0]
    with pytest.raises(ValueError, match="at least one value"):
        fisher_jenks_breaks([], 2)
    with pytest.raises(ValueError, match="between 1"):
        fisher_jenks_breaks(values, 0)
    with pytest.raises(ValueError, match="unique values"):
        fisher_jenks_breaks([1.0, 1.0, 1.0], 2)


def test_split_search_pydantic_validation() -> None:
    search = _SplitSearch(
        totals=[0.0, 1.0],
        squared_totals=[0.0, 1.0],
        best=[[0.0, 0.0]],
        splits=[[0, 0]],
    )
    assert search.totals == [0.0, 1.0]
    with pytest.raises(ValidationError):
        _SplitSearch(
            totals=[],
            squared_totals=[],
            best=[],
            splits=[],
            extra_field=True,  # type: ignore[call-arg]
        )
