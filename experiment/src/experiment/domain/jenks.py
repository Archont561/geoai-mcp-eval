"""Fisher-Jenks natural breaks: the pure algorithm, with no file access.

Lives in ``domain`` because two independent callers need it: the Arm A tool
catalogue (``gis_ops.jenks_breaks``) and the oracle's classification evaluator.
Keeping it in either one made that module depend on the other; here both
depend on it and neither depends on the other.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict


def _prefix_sums(values: list[float]) -> tuple[list[float], list[float]]:
    totals = [0.0]
    squared_totals = [0.0]
    for value in values:
        totals.append(totals[-1] + value)
        squared_totals.append(squared_totals[-1] + value * value)
    return totals, squared_totals


def _within_class_error(
    totals: list[float], squared_totals: list[float], start: int, end: int
) -> float:
    size = end - start
    total = totals[end] - totals[start]
    squares = squared_totals[end] - squared_totals[start]
    return max(0.0, squares - total * total / size)


class _SplitSearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    totals: list[float]
    squared_totals: list[float]
    best: list[list[float]]
    splits: list[list[int]]


def _inf_matrix(rows: int, cols: int) -> list[list[float]]:
    return [[math.inf] * cols for _ in range(rows)]


def _neg_one_matrix(rows: int, cols: int) -> list[list[int]]:
    return [[-1] * cols for _ in range(rows)]


def _find_jenks_splits(values: list[float], class_count: int) -> list[list[int]]:
    count = len(values)
    totals, squared_totals = _prefix_sums(values)
    width = count + 1
    search = _SplitSearch(
        totals=totals,
        squared_totals=squared_totals,
        best=_inf_matrix(class_count + 1, width),
        splits=_neg_one_matrix(class_count + 1, width),
    )
    search.best[0][0] = 0.0
    for groups in range(1, class_count + 1):
        for end in range(groups, count + 1):
            _update_best_split(groups, end, search)
    return search.splits


def _update_best_split(groups: int, end: int, search: _SplitSearch) -> None:
    for start in range(groups - 1, end):
        error = _within_class_error(search.totals, search.squared_totals, start, end)
        candidate = search.best[groups - 1][start] + error
        if candidate < search.best[groups][end] - 1e-9:
            search.best[groups][end] = candidate
            search.splits[groups][end] = start


def _recover_jenks_breaks(
    values: list[float], class_count: int, splits: list[list[int]]
) -> list[float]:
    boundaries: list[float] = []
    end = len(values)
    for groups in range(class_count, 0, -1):
        start = splits[groups][end]
        if start < 0:
            raise ValueError("could not partition Jenks input into the requested classes")
        boundaries.append(values[end - 1])
        end = start
    return list(reversed(boundaries))


def fisher_jenks_breaks(values: list[float], class_count: int) -> list[float]:
    """Compute optimal one-dimensional Fisher–Jenks upper bounds by dynamic programming."""
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        raise ValueError("Jenks input must contain at least one value")
    if class_count < 1 or class_count > len(set(sorted_values)):
        raise ValueError("class_count must be between 1 and the number of unique values")
    splits = _find_jenks_splits(sorted_values, class_count)
    return _recover_jenks_breaks(sorted_values, class_count, splits)
