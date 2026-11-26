"""Properties of the typed GIS operations exposed to study models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from shapely.geometry import box, mapping, shape

from experiment import gis_ops

FIXTURES = Path(__file__).resolve().parents[1] / "tasks" / "fixtures"
POL_CZE = json.loads((FIXTURES / "analysis/poland-czechia.geojson").read_text(encoding="utf-8"))
COUNTRIES = json.loads((FIXTURES / "cartography/countries.geojson").read_text(encoding="utf-8"))
point_features = st.builds(
    lambda x, y, code: {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [x, y]},
        "properties": {"ISO_A3": code},
    },
    st.integers(-180, 180),
    st.integers(-90, 90),
    st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=8),
)
collections = st.lists(point_features, min_size=1, max_size=8).map(
    lambda features: {"type": "FeatureCollection", "features": features}
)


def point_collection(x: int, y: int) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": {"name": "point"},
            }
        ],
    }


@example(collection=POL_CZE)
@example(collection=COUNTRIES)
@given(collection=collections)
def test_feature_information_and_point_outputs_preserve_features(collection: dict) -> None:
    features = collection["features"]
    info = gis_ops.feature_info(collection)
    assert info["feature_count"] == len(features)
    bounds = [shape(feature["geometry"]).bounds for feature in features]
    assert info["bbox"] == [
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    ]
    assert info["property_keys"] == sorted(
        {key for feature in features for key in feature["properties"]}
    )
    assert sum(info["geometry_types"].values()) == len(features)
    for operation in (gis_ops.centroid, gis_ops.representative_point):
        result = operation(collection)["features"]
        assert len(result) == len(features)
        assert all(feature["geometry"]["type"] == "Point" for feature in result)
        assert [feature["properties"] for feature in result] == [f["properties"] for f in features]


@given(kind=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20))
def test_feature_info_rejects_non_collections(kind: str) -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        gis_ops.feature_info({"type": kind})


@example(collection=POL_CZE, index=0, insensitive=False)
@example(collection=POL_CZE, index=1, insensitive=True)
@given(collection=collections, index=st.integers(min_value=0), insensitive=st.booleans())
def test_filter_selects_matching_values(collection: dict, index: int, insensitive: bool) -> None:
    features = collection["features"]
    code = features[index % len(features)]["properties"]["ISO_A3"]
    query = code.lower() if insensitive else code
    selected = gis_ops.filter_features(collection, "ISO_A3", query, case_insensitive=insensitive)
    assert selected["features"] == [f for f in features if f["properties"]["ISO_A3"] == code]
    assert gis_ops.filter_features(collection, "ISO_A3", "#")["features"] == []


@given(distance=st.floats(min_value=-100, max_value=-0.001, allow_nan=False, allow_infinity=False))
def test_negative_buffer_distance_is_rejected(distance: float) -> None:
    with pytest.raises(ValueError, match="distance"):
        gis_ops.buffer_geometries(POL_CZE, distance)


def rectangle_collection(x: int, y: int, width: int, height: int, label: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(box(x, y, x + width, y + height)),
                "properties": {"label": label},
            }
        ],
    }


@given(
    x=st.integers(-100, 100),
    y=st.integers(-100, 100),
    width=st.integers(1, 20),
    height=st.integers(1, 20),
    dx=st.integers(-25, 25),
    dy=st.integers(-25, 25),
)
def test_union_intersection_and_difference(
    x: int, y: int, width: int, height: int, dx: int, dy: int
) -> None:
    left = rectangle_collection(x, y, width, height, "left")
    right = rectangle_collection(x + dx, y + dy, width, height, "right")
    combined = {"type": "FeatureCollection", "features": left["features"] + right["features"]}
    a, b = (shape(item["features"][0]["geometry"]) for item in (left, right))
    union = gis_ops.union_geometries(combined)["features"][0]
    assert union["properties"]["n_inputs"] == 2
    assert shape(union["geometry"]).equals(a.union(b))
    assert shape(gis_ops.intersection(left, right)["features"][0]["geometry"]).equals(
        a.intersection(b)
    )
    assert shape(gis_ops.difference(left, right)["features"][0]["geometry"]).equals(a.difference(b))


@settings(deadline=None)
@given(dx=st.integers(-3, 3), dy=st.integers(-3, 3))
def test_spatial_join_properties_match_intersections(dx: int, dy: int) -> None:
    left = rectangle_collection(0, 0, 2, 2, "left")
    right = rectangle_collection(dx, dy, 2, 2, "right")
    joined = gis_ops.spatial_join_intersects(left, right)
    assert joined["type"] == "FeatureCollection"
    assert all(f["properties"]["right_label"] == "right" for f in joined["features"])
    assert bool(joined["features"]) == shape(left["features"][0]["geometry"]).intersects(
        shape(right["features"][0]["geometry"])
    )


@given(
    x=st.integers(-100, 100),
    y=st.integers(-100, 100),
    width=st.integers(1, 20),
    height=st.integers(1, 20),
)
def test_adjacent_rectangles_touch_symmetrically(x: int, y: int, width: int, height: int) -> None:
    left = rectangle_collection(x, y, width, height, "left")
    right = rectangle_collection(x + width, y, width, height, "right")
    for a, b in ((left, right), (right, left)):
        result = gis_ops.relate_de9im(a, b)
        assert result["relation"] == "touches"
        assert result["de9im"] == shape(a["features"][0]["geometry"]).relate(
            shape(b["features"][0]["geometry"])
        )


@given(
    values=st.lists(st.integers(-100, 100), min_size=1, max_size=20, unique=True), data=st.data()
)
def test_jenks_assignments_respect_breaks(values: list[int], data: st.DataObject) -> None:
    count = data.draw(st.integers(1, len(values)))
    result = gis_ops.jenks_breaks(values, count)
    assert result["method"] == "jenks"
    assert result["breaks"][-1] == max(values)
    assert result["assignments"] == [
        next(i for i, b in enumerate(result["breaks"], 1) if v <= b) for v in values
    ]


@given(count=st.integers(max_value=0), value=st.integers())
def test_jenks_rejects_empty_values_and_invalid_count(count: int, value: int) -> None:
    with pytest.raises(ValueError):
        gis_ops.jenks_breaks([], 2)
    with pytest.raises(ValueError):
        gis_ops.jenks_breaks([value], count)


@given(x=st.integers(-180, 180), y=st.integers(-90, 90))
def test_geographic_point_area_warns_and_nearest_is_self(x: int, y: int) -> None:
    collection = point_collection(x, y)
    report = gis_ops.area(collection)
    assert report["units"] == "m2-geodesic"
    assert report["per_feature"] == [0.0]
    assert report["warnings"] == ["feature 0: not a polygon; geodesic area reported as 0.0"]
    nearest = gis_ops.nearest_feature([x, y], collection)
    assert nearest["properties"]["name"] == "point"
    assert nearest["distance"] == 0


@given(point=st.lists(st.integers(), max_size=4).filter(lambda p: len(p) != 2))
def test_nearest_rejects_wrong_coordinate_count(point: list[int]) -> None:
    with pytest.raises(ValueError):
        gis_ops.nearest_feature(point, POL_CZE)


@given(kind=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20))
@example(kind="Bogus")
@example(kind="NotAGeometry")
def test_invalid_geometry_raises(kind: str) -> None:
    bad = point_collection(0, 0)
    bad["features"][0]["geometry"] = {"type": kind, "coordinates": [0]}
    with pytest.raises(ValueError):
        gis_ops.centroid(bad)


@given(operation=st.sampled_from([gis_ops.union_geometries, gis_ops._single_geometry]))
def test_union_operations_require_features(operation) -> None:
    with pytest.raises(ValueError):
        operation({"type": "FeatureCollection", "features": []})


@settings(deadline=None)
@given(
    code=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20).map(
        lambda suffix: "invalid-authority:" + suffix
    )
)
@example(code="EPSG:not-a-crs")
@example(code="EPSG:0")
@example(code="invalid")
def test_reproject_rejects_unknown_crs(code: str) -> None:
    with pytest.raises(ValueError, match="reprojection failed"):
        gis_ops.reproject(POL_CZE, code, "EPSG:2180")


@given(
    longitude=st.integers(min_value=-180, max_value=180),
    latitude=st.integers(min_value=-90, max_value=90),
)
@example(longitude=19, latitude=52)
def test_nearest_country_matches_geometry_distances(longitude: int, latitude: int) -> None:
    from shapely.geometry import Point

    nearest = gis_ops.nearest_feature([longitude, latitude], POL_CZE)
    distances = [
        shape(f["geometry"]).distance(Point(longitude, latitude)) for f in POL_CZE["features"]
    ]
    assert nearest["distance"] == min(distances)
    assert nearest["index"] == distances.index(min(distances))
    if (longitude, latitude) == (19, 52):
        assert nearest["properties"]["ISO_A3"] == "POL"
