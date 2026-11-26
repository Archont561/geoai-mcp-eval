"""Unit tests for ``experiment.oracle._jenks``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.oracle._jenks import jenks_assignments


@given(
    values=st.lists(
        st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=15,
    ),
    data=st.data(),
)
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_jenks_assignments_maps_every_feature_to_ordered_class(
    tmp_path: Path, values: list[float], data: st.DataObject
) -> None:
    unique_count = len(set(values))
    k = data.draw(st.integers(min_value=1, max_value=min(4, unique_count)))
    features = [
        {"type": "Feature", "properties": {"id": f"f{i}", "val": v}, "geometry": None}
        for i, v in enumerate(values)
    ]
    fixture = tmp_path / "gen.geojson"
    fixture.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    breaks, assignments = jenks_assignments(fixture, "id", "val", k)
    assert len(breaks) == k
    assert set(assignments) == {f"f{i}" for i in range(len(values))}
    assert all(1 <= cls <= k for cls in assignments.values())


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(start=1, gap=99)
@given(start=st.integers(-10000, 10000), gap=st.integers(min_value=3, max_value=10000))
def test_jenks_assignments_separates_well_spaced_pairs(
    tmp_path: Path, start: int, gap: int
) -> None:
    fixture = tmp_path / "pops.geojson"
    values = [start, start + 1, start + gap, start + gap + 1]
    fixture.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"id": name, "val": value}, "geometry": None}
                    for name, value in zip(("a", "b", "c", "d"), values, strict=True)
                ],
            }
        ),
        encoding="utf-8",
    )
    breaks, assignments = jenks_assignments(fixture, "id", "val", 2)
    assert breaks == [float(start + 1), float(start + gap + 1)]
    assert assignments == {"a": 1, "b": 1, "c": 2, "d": 2}


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(identifier="a", first=1, second=2)
@given(
    identifier=st.text(min_size=1, max_size=20),
    first=st.integers(-1000, 1000),
    second=st.integers(-1000, 1000),
)
def test_jenks_assignments_rejects_duplicate_identifiers(
    tmp_path: Path, identifier: str, first: int, second: int
) -> None:
    fixture = tmp_path / "dup.geojson"
    fixture.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": identifier, "val": value},
                        "geometry": None,
                    }
                    for value in (first, second)
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        jenks_assignments(fixture, "id", "val", 2)
