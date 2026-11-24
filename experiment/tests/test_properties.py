"""Property-based tests (hypothesis) for the pilot oracle's pure internals."""

from __future__ import annotations

import json
import math
import tempfile
from itertools import combinations
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from shapely.geometry import shape
from shapely.ops import unary_union

from experiment import gis_ops
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


# --- GIS operations -----------------------------------------------------------
#
# The invariants below hold for *every* input the strategy can draw, so they
# catch an operation that is subtly wrong on some geometry rather than on the
# one example a hand-written test picked. Two traps found while writing them:
#
#   - ``buffer_geometries`` is NOT monotone in vertex count (441 -> 372 between
#     distance 0.5 and 1.0), because GeoPandas simplifies as it resamples. The
#     monotone quantity is the buffered *area*.
#   - ``union_geometries`` is idempotent in geometry but not as a document:
#     re-unioning rewrites ``properties`` ({'n_inputs': 2} -> {'n_inputs': 1}).
#     Assert on the geometry, never on the FeatureCollection.

GIS_FIXTURES = Path(__file__).resolve().parents[1] / "tasks" / "fixtures"


def _fixture(relative: str) -> dict:
    return json.loads((GIS_FIXTURES / relative).read_text(encoding="utf-8"))


POLAND_CZECHIA = _fixture("analysis/poland-czechia.geojson")
COUNTRIES = _fixture("cartography/countries.geojson")


def _union_of(collection: dict):
    return unary_union([shape(feature["geometry"]) for feature in collection["features"]])


@given(distance=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False))
def test_buffer_grows_monotonically_and_keeps_the_input(distance: float) -> None:
    """A larger buffer covers strictly more area and always contains the original."""
    original = _union_of(POLAND_CZECHIA)
    buffered = _union_of(gis_ops.buffer_geometries(POLAND_CZECHIA, distance))
    larger = _union_of(gis_ops.buffer_geometries(POLAND_CZECHIA, distance + 0.5))
    assert buffered.buffer(1e-12).contains(original)
    assert larger.area >= buffered.area - 1e-12


@given(distance=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_buffering_never_drops_a_feature(distance: float) -> None:
    buffered = gis_ops.buffer_geometries(POLAND_CZECHIA, distance)
    assert len(buffered["features"]) == len(POLAND_CZECHIA["features"])


@given(
    crs=st.sampled_from(["EPSG:2180", "EPSG:3857", "EPSG:32634"]),
)
def test_reproject_round_trip_restores_the_bounding_box(crs: str) -> None:
    """Projection is lossy in the last digits only; the bbox must come back."""
    projected = gis_ops.reproject(POLAND_CZECHIA, "EPSG:4326", crs)
    restored = gis_ops.reproject(projected, crs, "EPSG:4326")
    original_box = gis_ops._bbox_of(POLAND_CZECHIA["features"])
    restored_box = gis_ops._bbox_of(restored["features"])
    assert all(abs(a - b) < 1e-6 for a, b in zip(original_box, restored_box, strict=True))


@given(crs=st.sampled_from(["EPSG:2180", "EPSG:32634"]))
def test_geodesic_and_projected_area_agree(crs: str) -> None:
    """The two area modes are independent code paths; they must not diverge.

    Only equal-area or near-conformal projections belong here. EPSG:3857 is
    emphatically not one: its area scale factor is ~1/cos^2(latitude), so at
    Poland it reports 2.6x the true area. Asserting agreement there would pin
    a projection property, not a property of the ``area`` operation.
    """
    geodesic = gis_ops.area(POLAND_CZECHIA)
    planar = gis_ops.area(gis_ops.reproject(POLAND_CZECHIA, "EPSG:4326", crs))
    assert geodesic["units"] == "m2-geodesic"
    assert planar["units"] == "crs-units"
    assert math.isclose(geodesic["total"], planar["total"], rel_tol=1e-3)


def test_union_is_idempotent_in_geometry() -> None:
    once = gis_ops.union_geometries(POLAND_CZECHIA)
    twice = gis_ops.union_geometries(once)
    assert shape(once["features"][0]["geometry"]).equals(shape(twice["features"][0]["geometry"]))
    assert len(once["features"]) == 1


@given(iso_a3=st.sampled_from([f["properties"]["ISO_A3"] for f in COUNTRIES["features"]]))
def test_filter_returns_a_subsequence_of_the_input(iso_a3: str) -> None:
    """Filtering never invents a feature and never reorders the survivors."""
    input_ids = [feature["properties"]["ISO_A3"] for feature in COUNTRIES["features"]]
    filtered = gis_ops.filter_features(COUNTRIES, "ISO_A3", iso_a3)
    output_ids = [feature["properties"]["ISO_A3"] for feature in filtered["features"]]
    assert output_ids, f"{iso_a3} is in the fixture, so it must survive its own filter"
    assert set(output_ids) <= set(input_ids)
    assert output_ids == [value for value in input_ids if value in set(output_ids)]


def test_centroid_of_every_country_lies_inside_its_bounding_box() -> None:
    centroids = gis_ops.centroid(COUNTRIES)
    bounds = {
        feature["properties"]["ISO_A3"]: shape(feature["geometry"]).bounds
        for feature in COUNTRIES["features"]
    }
    assert len(centroids["features"]) == len(COUNTRIES["features"])
    for feature in centroids["features"]:
        point = shape(feature["geometry"])
        min_x, min_y, max_x, max_y = bounds[feature["properties"]["ISO_A3"]]
        assert min_x <= point.x <= max_x and min_y <= point.y <= max_y


@given(longitude=st.floats(-180.0, 180.0), latitude=st.floats(-90.0, 90.0))
def test_nearest_feature_is_never_negative_distance(longitude: float, latitude: float) -> None:
    """The nearest feature exists for any point on Earth and cannot be behind it."""
    nearest = gis_ops.nearest_feature([longitude, latitude], COUNTRIES)
    assert 0 <= nearest["index"] < len(COUNTRIES["features"])
    assert nearest["distance"] >= 0.0


def test_the_operation_registry_is_the_advertised_catalogue() -> None:
    """Arm A is measured against exactly these operations; 14 is the frozen count."""
    assert len(gis_ops.OPS) == 14
    assert set(gis_ops.OPS) == {
        "area",
        "buffer_geometries",
        "centroid",
        "difference",
        "feature_info",
        "filter_features",
        "intersection",
        "jenks_breaks",
        "nearest_feature",
        "relate_de9im",
        "reproject",
        "representative_point",
        "spatial_join_intersects",
        "union_geometries",
    }
