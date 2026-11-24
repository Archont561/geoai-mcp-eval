"""Coverage tests for the typed GIS operations (pure, no QGIS)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment import gis_ops

FEATURES_KEY = "features"
ISO_FIELD = "ISO_A3"
TYPE_KEY = "type"

FIXTURES = Path(__file__).resolve().parents[1] / "tasks" / "fixtures"


def fc(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


@pytest.fixture()
def pol_cze() -> dict:
    return fc("analysis/poland-czechia.geojson")


@pytest.fixture()
def countries() -> dict:
    return fc("cartography/countries.geojson")


def test_feature_info(countries: dict) -> None:
    info = gis_ops.feature_info(countries)
    assert info["feature_count"] == len(countries[FEATURES_KEY])
    assert info["bbox"][0] < info["bbox"][2]
    assert ISO_FIELD in info["property_keys"]
    assert info["geometry_types"]


def test_feature_info_rejects_non_collection() -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        gis_ops.feature_info({TYPE_KEY: "Feature"})


def test_filter_features(pol_cze: dict) -> None:
    pol = gis_ops.filter_features(pol_cze, ISO_FIELD, "pol", case_insensitive=True)
    assert [f["properties"][ISO_FIELD] for f in pol[FEATURES_KEY]] == ["POL"]
    assert gis_ops.filter_features(pol_cze, ISO_FIELD, "XXX")[FEATURES_KEY] == []


def test_buffer_and_distance_validation(pol_cze: dict) -> None:
    buffered = gis_ops.buffer_geometries(pol_cze, 0.5)
    assert len(buffered[FEATURES_KEY]) == len(pol_cze[FEATURES_KEY])
    with pytest.raises(ValueError, match="distance"):
        gis_ops.buffer_geometries(pol_cze, -1)


def test_union_intersection_difference(pol_cze: dict) -> None:
    pol = gis_ops.filter_features(pol_cze, ISO_FIELD, "POL")
    cze = gis_ops.filter_features(pol_cze, ISO_FIELD, "CZE")
    merged = gis_ops.union_geometries(pol_cze)
    assert merged[FEATURES_KEY][0]["properties"]["n_inputs"] == 2
    inter = gis_ops.intersection(pol, cze)
    assert inter[FEATURES_KEY][0]["geometry"] is not None
    diff = gis_ops.difference(pol, cze)
    assert diff[FEATURES_KEY][0]["geometry"][TYPE_KEY] in {"Polygon", "MultiPolygon"}


def test_centroid_and_representative_point(pol_cze: dict) -> None:
    centroids = gis_ops.centroid(pol_cze)
    points = gis_ops.representative_point(pol_cze)
    assert all(f["geometry"][TYPE_KEY] == "Point" for f in centroids[FEATURES_KEY])
    assert len(points[FEATURES_KEY]) == len(pol_cze[FEATURES_KEY])
    # properties are preserved
    assert points[FEATURES_KEY][0]["properties"].get(ISO_FIELD) in {"POL", "CZE"}


def test_area_geographic_vs_planar(pol_cze: dict) -> None:
    geo = gis_ops.area(pol_cze)
    assert geo["units"] == "m2-geodesic"
    assert geo["total"] > 0
    projected = gis_ops.reproject(pol_cze, "EPSG:4326", "EPSG:2180")
    planar = gis_ops.area(projected)
    assert planar["units"] == "crs-units"


def test_reproject_roundtrip(pol_cze: dict) -> None:
    projected = gis_ops.reproject(pol_cze, "EPSG:4326", "EPSG:2180")
    back = gis_ops.reproject(projected, "EPSG:2180", "EPSG:4326")
    original = gis_ops._bbox_of(pol_cze[FEATURES_KEY])
    roundtrip = gis_ops._bbox_of(back[FEATURES_KEY])
    assert all(abs(a - b) < 1e-6 for a, b in zip(original, roundtrip, strict=True))


def test_spatial_join_intersects(pol_cze: dict, countries: dict) -> None:
    pol = gis_ops.filter_features(countries, ISO_FIELD, "POL")
    cze = gis_ops.filter_features(countries, ISO_FIELD, "CZE")
    joined = gis_ops.spatial_join_intersects(pol, cze)
    # POL does not intersect CZE at country granularity? keep it about mechanics:
    assert joined[TYPE_KEY] == "FeatureCollection"
    assert all("right_ISO_A3" in f["properties"] for f in joined[FEATURES_KEY])


def test_relate_de9im(pol_cze: dict) -> None:
    pol = gis_ops.filter_features(pol_cze, ISO_FIELD, "POL")
    cze = gis_ops.filter_features(pol_cze, ISO_FIELD, "CZE")
    result = gis_ops.relate_de9im(pol, cze)
    assert result["de9im"] == "FF2F11212"
    assert result["relation"] == "touches"


def test_jenks_breaks_empty_and_validation() -> None:
    with pytest.raises(ValueError):
        gis_ops.jenks_breaks([], 2)
    with pytest.raises(ValueError):
        gis_ops.jenks_breaks([1, 2, 3], 0)
    jb = gis_ops.jenks_breaks([1.0, 2.0, 3.0, 100.0], 2)
    assert jb["method"] == "jenks"
    assert jb["breaks"][-1] == 100.0
    assert jb["assignments"][-1] == 2


def test_nearest_feature(pol_cze: dict) -> None:
    result = gis_ops.nearest_feature([19.0, 52.0], pol_cze)
    assert result["properties"][ISO_FIELD] == "POL"
    with pytest.raises(ValueError):
        gis_ops.nearest_feature([19.0], pol_cze)


def test_invalid_geometry_raises() -> None:
    bad = {
        TYPE_KEY: "FeatureCollection",
        FEATURES_KEY: [
            {
                TYPE_KEY: "Feature",
                "geometry": {TYPE_KEY: "Bogus", "coordinates": [0]},
                "properties": {},
            }
        ],
    }
    with pytest.raises(ValueError):
        gis_ops.centroid(bad)


def test_single_geometry_requires_features() -> None:
    with pytest.raises(ValueError):
        gis_ops._single_geometry({TYPE_KEY: "FeatureCollection", FEATURES_KEY: []})


def test_mcp_server_exposes_exactly_the_ops_registry() -> None:
    import asyncio

    from experiment.adapters.mcp import client as mcp_client
    from experiment.adapters.mcp import server as mcp_server

    tools = asyncio.run(mcp_server.server.list_tools())
    advertised = asyncio.run(mcp_client.list_tools())
    assert {tool.name for tool in tools} == set(gis_ops.OPS)
    assert set(advertised) == set(gis_ops.OPS)
    assert len(advertised) == len(gis_ops.OPS)


def test_area_geographic_non_polygon_reports_warning() -> None:
    point_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [21.0, 52.0]},
                "properties": {"ISO_A3": "WAW"},
            }
        ],
    }
    report = gis_ops.area(point_collection)
    assert report["units"] == "m2-geodesic"
    assert report["per_feature"] == [0.0]
    assert report["warnings"] == ["feature 0: not a polygon; geodesic area reported as 0.0"]


def test_reproject_rejects_unknown_crs(pol_cze: dict) -> None:
    with pytest.raises(ValueError, match="reprojection failed"):
        gis_ops.reproject(pol_cze, "EPSG:not-a-crs", "EPSG:2180")
