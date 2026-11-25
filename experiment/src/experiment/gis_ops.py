"""Typed GIS operations exposed by the prototype MCP server.

Every operation takes plain JSON-like inputs (GeoJSON mappings, numbers,
strings) and returns plain JSON-like outputs, so they can be registered as
MCP tools without any QGIS dependency. Geometry semantics follow Shapely 2;
inputs are assumed to be WGS84 longitude/latitude unless a CRS is passed to
`reproject`. All functions raise ValueError on bad input — callers (MCP
server, CLI) surface that message verbatim.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import geopandas as gpd
import pyproj
from shapely import make_valid, relate
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

from experiment.domain.jenks import fisher_jenks_breaks
from experiment.domain.task_validation import De9imRelation

GeoJSON = dict[str, Any]

_PROPS = "properties"

_DE9IM_PREDICATES = ["equals", "touches", "within", "contains", "crosses", "overlaps", "intersects"]


def _matrix_override(predicate: str) -> str | None:
    try:
        return De9imRelation(predicate).matrix_override()
    except ValueError:
        return None


def _ensure_feature_maps(features: object) -> list[dict[str, Any]]:
    if not isinstance(features, list) or not all(isinstance(f, dict) for f in features):
        raise ValueError("features must be a list of GeoJSON Feature objects")
    return features


def _is_num(value: object) -> bool:
    return isinstance(value, (int, float))


def _features(geojson: GeoJSON) -> list[dict[str, Any]]:
    if not isinstance(geojson, dict):
        raise ValueError("expected a GeoJSON object")
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("expected a GeoJSON FeatureCollection")
    return _ensure_feature_maps(geojson.get("features"))


def _geometry_of(feature: dict[str, Any]) -> Any:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("each feature must have a geometry object")
    try:
        return shape(geometry)
    except Exception as exc:  # shapely raises GEOSException / ValueError
        raise ValueError(f"invalid geometry: {exc}") from exc


def _to_frame(features: list[dict[str, Any]], crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    geometries = [_geometry_of(f) for f in features]
    properties = [f.get(_PROPS) if isinstance(f.get(_PROPS), dict) else {} for f in features]
    return gpd.GeoDataFrame(properties, geometry=geometries, crs=crs)


def _fc_from(geoms: list[Any], properties: list[dict[str, Any] | None]) -> GeoJSON:
    features = []
    for geom, props in zip(geoms, properties, strict=True):
        features.append({"type": "Feature", "geometry": mapping(geom), _PROPS: props or {}})
    return {"type": "FeatureCollection", "features": features}


def _union_features(features: list[dict[str, Any]]) -> Any:
    if not features:
        raise ValueError("expected at least one feature")
    geometries = [_geometry_of(f) for f in features]
    return unary_union([g for g in geometries if not g.is_empty])


def _single_geometry(geojson: GeoJSON) -> Any:
    return _union_features(_features(geojson))


def _bbox_of(features: list[dict[str, Any]]) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    for f in features:
        xs.extend(_axis(f, 0))
        ys.extend(_axis(f, 1))
    if not xs:
        raise ValueError("no coordinates found")
    return [min(xs), min(ys), max(xs), max(ys)]


def _axis(feature: dict[str, Any], index: int, out: list[float] | None = None) -> list[float]:
    out = out if out is not None else []

    def walk(coords: Any) -> None:
        if _is_num(coords):
            return
        if isinstance(coords, list):
            if coords and _is_num(coords[0]):
                out.append(float(coords[index]))
            else:
                for c in coords:
                    walk(c)

    walk(feature["geometry"].get("coordinates"))
    return out


def _looks_geographic(features: list[dict[str, Any]]) -> bool:
    """Heuristic: bbox inside lon/lat ranges => treat input as WGS84.

    Prototype-grade: a small projected CRS whose coordinates happen to fall
    inside [-180, 180] x [-90, 90] (e.g. EPSG:3857 near the origin) is
    indistinguishable from WGS84 by bbox alone, so area() would report
    geodesic m^2 for projected input. Callers that know the CRS must
    reproject explicitly; this guess exists only for the no-CRS-metadata path.
    """
    minx, miny, maxx, maxy = _bbox_of(features)
    lon_ok = minx >= -180 and maxx <= 180
    lat_ok = miny >= -90 and maxy <= 90
    return lon_ok and lat_ok


_GEODESIC = pyproj.Geod(ellps="WGS84")


def feature_info(geojson: GeoJSON) -> dict[str, Any]:
    """Profile a FeatureCollection: feature count, bbox, property keys, geometry types."""
    features = _features(geojson)
    types = Counter(f.get("geometry", {}).get("type") for f in features)
    props = sorted({k for f in features for k in (f.get(_PROPS) or {})})
    return {
        "feature_count": len(features),
        "bbox": _bbox_of(features) if features else [],
        "geometry_types": dict(sorted(types.items())),
        "property_keys": props,
    }


def filter_features(
    geojson: GeoJSON, property: str, equals: Any, case_insensitive: bool = False
) -> GeoJSON:
    """Select features where properties[property] equals `equals` (optionally case-insensitive)."""
    features = _features(geojson)

    def matches(value: Any) -> bool:
        if case_insensitive and isinstance(value, str) and isinstance(equals, str):
            return value.lower() == equals.lower()
        return value == equals

    selected = [f for f in features if matches((f.get(_PROPS) or {}).get(property))]
    return {"type": "FeatureCollection", "features": selected}


def buffer_geometries(geojson: GeoJSON, distance: float) -> GeoJSON:
    """Buffer all geometries by DISTANCE. Units match the input CRS (degrees for WGS84)."""
    if distance < 0:
        raise ValueError("distance must be non-negative")
    features = _features(geojson)
    geoms = [_geometry_of(f).buffer(distance) for f in features]
    return _fc_from(geoms, [f.get(_PROPS) for f in features])


def union_geometries(geojson: GeoJSON) -> GeoJSON:
    """Union all geometries into a single multipart geometry (one feature out)."""
    features = _features(geojson)
    geom = _union_features(features)
    return _fc_from([make_valid(geom)], [{"op": "union", "n_inputs": len(features)}])


def intersection(geojson_a: GeoJSON, geojson_b: GeoJSON) -> GeoJSON:
    """Intersection of the unions of two FeatureCollections (single feature out)."""
    geom = _single_geometry(geojson_a).intersection(_single_geometry(geojson_b))
    return _fc_from([geom], [{"op": "intersection"}])


def difference(geojson_a: GeoJSON, geojson_b: GeoJSON) -> GeoJSON:
    """Geometries of A minus B (single unioned feature out)."""
    geom = _single_geometry(geojson_a).difference(_single_geometry(geojson_b))
    return _fc_from([geom], [{"op": "difference"}])


def centroid(geojson: GeoJSON) -> GeoJSON:
    """Area-weighted centroid of each geometry; preserves properties."""
    features = _features(geojson)
    return _fc_from(
        [_geometry_of(f).centroid for f in features],
        [f.get(_PROPS) for f in features],
    )


def representative_point(geojson: GeoJSON) -> GeoJSON:
    """Interior point guaranteed to lie inside each geometry; preserves properties."""
    features = _features(geojson)
    return _fc_from(
        [_geometry_of(f).representative_point() for f in features],
        [f.get(_PROPS) for f in features],
    )


def area(geojson: GeoJSON) -> dict[str, Any]:
    """Area per feature and total. Geographic inputs get geodesic m^2, others planar CRS units."""
    features = _features(geojson)
    geographic = _looks_geographic(features)
    areas: list[float] = []
    not_polygon: list[int] = []
    for index, f in enumerate(features):
        geom = _geometry_of(f)
        if geographic:
            if geom.geom_type not in {"Polygon", "MultiPolygon"}:
                areas.append(0.0)
                not_polygon.append(index)
                continue
            area_m2, _ = _GEODESIC.geometry_area_perimeter(geom)
            areas.append(abs(area_m2))
        else:
            areas.append(geom.area)
    report: dict[str, Any] = {
        "units": "m2-geodesic" if geographic else "crs-units",
        "per_feature": areas,
        "total": sum(areas),
    }
    if not_polygon:
        report["warnings"] = [
            f"feature {i}: not a polygon; geodesic area reported as 0.0" for i in not_polygon
        ]
    return report


def reproject(geojson: GeoJSON, from_crs: str, to_crs: str) -> GeoJSON:
    """Reproject a FeatureCollection, e.g. from_crs='EPSG:4326' to_crs='EPSG:2180'."""
    features = _features(geojson)
    try:
        frame = _to_frame(features, crs=from_crs).to_crs(to_crs)
    except Exception as exc:
        raise ValueError(f"reprojection failed: {exc}") from exc
    return json.loads(frame.to_json())


def spatial_join_intersects(left: GeoJSON, right: GeoJSON) -> GeoJSON:
    """Inner join on intersects; right props merged as `right_*`."""
    left_features = _features(left)
    right_features = _features(right)
    left_frame = _to_frame(left_features)
    right_frame = _to_frame(right_features).add_prefix("right_")
    right_frame = right_frame.set_geometry("right_geometry").rename_geometry("geometry")
    joined = gpd.sjoin(left_frame, right_frame, predicate="intersects", how="inner")
    joined = joined.drop(columns=[c for c in ["index_right"] if c in joined.columns])
    return json.loads(joined.to_json())


def relate_de9im(geojson_a: GeoJSON, geojson_b: GeoJSON) -> dict[str, Any]:
    """DE-9IM relation matrix and name between the unions of A and B (e.g. 'touches')."""
    a = _single_geometry(geojson_a)
    b = _single_geometry(geojson_b)
    matrix = relate(a, b)
    name = "disjoint"
    for predicate in _DE9IM_PREDICATES:
        override = _matrix_override(predicate)
        matches = (override is not None and str(matrix) == override) or getattr(a, predicate)(b)
        if matches:
            name = predicate
            break
    return {"de9im": str(matrix), "relation": name}


def jenks_breaks(values: list[float], class_count: int = 4) -> dict[str, Any]:
    """Fisher–Jenks natural breaks (optimal DP): upper bounds + per-value classes."""
    numbers = [float(v) for v in values]
    if not numbers:
        raise ValueError("values must be a non-empty list of numbers")
    if class_count < 1:
        raise ValueError("class_count must be >= 1")
    breaks = fisher_jenks_breaks(numbers, class_count)
    classes = [next(i for i, upper in enumerate(breaks, start=1) if v <= upper) for v in numbers]
    return {"method": "jenks", "class_count": len(breaks), "breaks": breaks, "assignments": classes}


def nearest_feature(point: list[float], geojson: GeoJSON) -> dict[str, Any]:
    """Nearest feature to POINT ([x, y] in the input CRS) with distance in CRS units."""
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError("point must be [x, y]")
    features = _features(geojson)
    if not features:
        raise ValueError("expected at least one feature")
    pt = Point(float(point[0]), float(point[1]))
    best_index, best_distance = min(
        enumerate(_geometry_of(f).distance(pt) for f in features),
        key=lambda item: item[1],
    )
    return {
        "index": best_index,
        "distance": best_distance,
        _PROPS: features[best_index].get(_PROPS, {}),
    }


OPS: dict[str, Any] = {
    "feature_info": feature_info,
    "filter_features": filter_features,
    "buffer_geometries": buffer_geometries,
    "union_geometries": union_geometries,
    "intersection": intersection,
    "difference": difference,
    "centroid": centroid,
    "representative_point": representative_point,
    "area": area,
    "reproject": reproject,
    "spatial_join_intersects": spatial_join_intersects,
    "relate_de9im": relate_de9im,
    "jenks_breaks": jenks_breaks,
    "nearest_feature": nearest_feature,
}
