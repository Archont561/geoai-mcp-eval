"""Unit tests for ``experiment.oracle._jenks``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.oracle._jenks import jenks_assignments


def test_jenks_assignments_classifies_geojson_fixture_and_rejects_bad_rows(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "pops.geojson"
    fixture.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"id": "a", "val": 1.0}, "geometry": None},
                    {"type": "Feature", "properties": {"id": "b", "val": 2.0}, "geometry": None},
                    {"type": "Feature", "properties": {"id": "c", "val": 100.0}, "geometry": None},
                    {"type": "Feature", "properties": {"id": "d", "val": 101.0}, "geometry": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    breaks, assignments = jenks_assignments(fixture, "id", "val", 2)
    assert breaks == [2.0, 101.0]
    assert assignments == {"a": 1, "b": 1, "c": 2, "d": 2}

    dup = tmp_path / "dup.geojson"
    dup.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"id": "a", "val": 1.0}, "geometry": None},
                    {"type": "Feature", "properties": {"id": "a", "val": 2.0}, "geometry": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        jenks_assignments(dup, "id", "val", 2)
