"""Fisher-Jenks classification of a GeoJSON fixture, for the pilot oracle.

The algorithm itself lives in :mod:`experiment.domain.jenks`; this module only
maps a fixture's properties onto it.
"""

from __future__ import annotations

from pathlib import Path

from experiment.domain.jenks import fisher_jenks_breaks as fisher_jenks_breaks

from ._base import geojson_features


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
