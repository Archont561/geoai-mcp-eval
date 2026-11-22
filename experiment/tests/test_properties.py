"""Property-based tests (hypothesis) for the pilot oracle's pure internals."""

from __future__ import annotations

import math
import tempfile
from itertools import combinations
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from experiment.harness import extract_iso
from experiment.oracle import fisher_jenks_breaks
from experiment.oracle._base import safe_path

FINITE_FLOATS = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
SMALL_VALUE_LISTS = st.lists(st.integers(-1000, 1000), min_size=1, max_size=9)

PATH_ROOT = Path(tempfile.mkdtemp(prefix="properties-path-root-"))
PATH_SEGMENTS = st.text(alphabet="abcXYZ019_-", min_size=1, max_size=8)
SAFE_RELATIVE = st.lists(PATH_SEGMENTS, min_size=1, max_size=4)


def _class_index(breaks: list[float], value: float) -> int:
    return next(index for index, upper in enumerate(breaks, start=1) if value <= upper)


def _within_class_ss(values: list[float]) -> float:
    if not values:
        return 0.0
    total = sum(values)
    mean = total / len(values)
    return sum((value - mean) ** 2 for value in values)


def _partition_cost(sorted_values: list[float], cuts: tuple[int, ...]) -> float:
    boundaries = (0, *cuts, len(sorted_values))
    total = 0.0
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        total += _within_class_ss(sorted_values[start:end])
    return total


def _brute_force_cost(sorted_values: list[float], class_count: int) -> float:
    gaps = range(1, len(sorted_values))
    return min(_partition_cost(sorted_values, cuts) for cuts in combinations(gaps, class_count - 1))


def _class_count(values: list[float], ceiling: int = 4) -> int:
    return min(ceiling, len(set(values)))


@given(values=st.lists(FINITE_FLOATS, min_size=1, max_size=60))
def test_breaks_are_non_decreasing_upper_bounds_from_the_data(values: list[float]) -> None:
    class_count = _class_count(values)
    breaks = fisher_jenks_breaks(values, class_count)
    assert len(breaks) == class_count
    assert breaks == sorted(breaks)
    assert all(break_value in set(values) for break_value in breaks)


@given(values=st.lists(FINITE_FLOATS, min_size=1, max_size=60))
def test_every_value_lands_in_a_valid_class(values: list[float]) -> None:
    class_count = _class_count(values)
    breaks = fisher_jenks_breaks(values, class_count)
    assignments = [_class_index(breaks, value) for value in values]
    assert all(1 <= index <= class_count for index in assignments)


@given(values=SMALL_VALUE_LISTS, data=st.data())
@settings(max_examples=200)
def test_jenks_cost_matches_brute_force(values: list[int], data) -> None:
    sorted_values = sorted(float(value) for value in values)
    unique_count = len(set(sorted_values))
    class_count = data.draw(st.integers(min_value=1, max_value=min(3, unique_count)))
    breaks = fisher_jenks_breaks(sorted_values, class_count)
    classes: list[list[float]] = [[] for _ in range(class_count)]
    for value in sorted_values:
        classes[_class_index(breaks, value) - 1].append(value)
    dp_cost = sum(_within_class_ss(group) for group in classes)
    brute_cost = _brute_force_cost(sorted_values, class_count)
    assert math.isclose(dp_cost, brute_cost, rel_tol=1e-6, abs_tol=1e-6)


@given(values=SMALL_VALUE_LISTS)
def test_breaks_partition_into_exactly_class_count_non_empty_classes(values: list[int]) -> None:
    sorted_values = sorted(float(value) for value in values)
    class_count = _class_count(sorted_values, ceiling=3)
    breaks = fisher_jenks_breaks(sorted_values, class_count)
    classes = [[] for _ in range(class_count)]
    for value in sorted_values:
        classes[_class_index(breaks, value) - 1].append(value)
    assert all(group for group in classes)


@given(values=st.lists(st.integers(-1000, 1000), min_size=1, max_size=20, unique=True))
def test_class_count_equal_to_unique_values_recovers_every_value(values: list[int]) -> None:
    breaks = fisher_jenks_breaks([float(value) for value in values], len(values))
    assert breaks == sorted(float(value) for value in values)


@given(values=st.lists(FINITE_FLOATS, min_size=1, max_size=30))
def test_determinism(values: list[float]) -> None:
    class_count = _class_count(values)
    first = fisher_jenks_breaks(values, class_count)
    second = fisher_jenks_breaks(list(values), class_count)
    assert first == second


@given(data=st.data())
def test_class_count_above_unique_values_raises(data) -> None:
    values = data.draw(st.lists(st.integers(-100, 100), min_size=1, max_size=10))
    unique_count = len(set(values))
    with pytest.raises(ValueError):
        fisher_jenks_breaks([float(value) for value in values], unique_count + 1)


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        fisher_jenks_breaks([], 1)
    with pytest.raises(ValueError):
        fisher_jenks_breaks([1.0], 0)


@given(segments=SAFE_RELATIVE)
def test_relative_paths_stay_inside_root(segments: list[str]) -> None:
    candidate = "/".join(segments)
    resolved = safe_path(PATH_ROOT, candidate)
    assert resolved.is_relative_to(PATH_ROOT.resolve())


@given(depth=st.integers(min_value=1, max_value=8), prefix=st.integers(min_value=0, max_value=4))
def test_escaping_paths_raise(depth: int, prefix: int) -> None:
    assume(depth > prefix)
    candidate = "/".join(["sub"] * prefix + [".."] * depth + ["escape.txt"])
    with pytest.raises(ValueError):
        safe_path(PATH_ROOT, candidate)


@given(name=st.text(alphabet="abcXYZ019_-", min_size=1, max_size=12))
def test_absolute_paths_raise(name: str) -> None:
    with pytest.raises(ValueError):
        safe_path(PATH_ROOT, f"/{name}")


@given(
    payload=st.lists(
        st.tuples(
            st.text(alphabet="abc_", min_size=1, max_size=6),
            st.text(alphabet="ABC_", min_size=1, max_size=3),
        ),
        min_size=0,
        max_size=10,
    )
)
def test_extract_iso_preserves_order_and_values(payload: list[tuple[str, str]]) -> None:
    features = [{"properties": {"ISO_A3": iso}} for _, iso in payload]
    assert extract_iso(features) == [iso for _, iso in payload]
