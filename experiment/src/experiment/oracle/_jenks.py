"""Fisher-Jenks natural breaks implementation used by the pilot oracle."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from ._base import geojson_features


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


@dataclass(frozen=True)
class _SplitSearch:
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


def _feature_properties(feature: dict[str, object]) -> dict[str, object]:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("each input feature must have a properties object")
    return properties


def _is_numeric_value(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _feature_value(
    properties: dict[str, object], id_field: str, value_field: str
) -> tuple[str, float]:
    identifier = properties.get(id_field)
    value = properties.get(value_field)
    if not isinstance(identifier, str) or not _is_numeric_value(value):
        raise ValueError(f"feature requires string {id_field} and numeric {value_field}")
    return identifier, float(value)


def jenks_assignments(
    fixture: Path,
    id_field: str,
    value_field: str,
    class_count: int,
) -> tuple[list[float], dict[str, int]]:
    features = geojson_features(fixture)
    values = [
        _feature_value(_feature_properties(feature), id_field, value_field) for feature in features
    ]
    if len({identifier for identifier, _ in values}) != len(values):
        raise ValueError(f"input {id_field} values must be unique")
    breaks = fisher_jenks_breaks([value for _, value in values], class_count)
    assignments = {
        identifier: next(index for index, upper in enumerate(breaks, start=1) if value <= upper)
        for identifier, value in values
    }
    return breaks, assignments
