"""Prototype GIS MCP server — exposes the typed operations in gis_ops.

Run over stdio:

    python -m experiment.adapters.mcp.server

The server is deliberately stateless: every tool takes a GeoJSON mapping (or a
list of values) and returns a JSON mapping; there is no catalogue hash registry
or enforcement middleware yet (that is decision 0004's job, post-freeze). This
is the Arm A surface the prototype agent talks to.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from experiment import gis_ops

server = MCPServer(
    name="gis-prototype",
    title="GIS Prototype Operations",
    description="Typed GIS operations. Prototype catalogue — not frozen.",
    version="0.1.0",
    instructions=(
        "GeoJSON FeatureCollections are passed as JSON objects. Tools never "
        "fetch external data; the fixture GeoJSON is the only allowed input. "
        "Coordinates are WGS84 longitude/latitude unless a CRS argument is given."
    ),
)


@server.tool()
def feature_info(geojson: dict[str, Any]) -> dict[str, Any]:
    """Profile a FeatureCollection: feature count, bbox, geometry types, property keys."""
    return gis_ops.feature_info(geojson)


@server.tool()
def filter_features(
    geojson: dict[str, Any], property: str, equals: Any, case_insensitive: bool = False
) -> dict[str, Any]:
    """Select features where properties[property] equals equals (optionally case-insensitive)."""
    return gis_ops.filter_features(geojson, property, equals, case_insensitive)


@server.tool()
def buffer_geometries(geojson: dict[str, Any], distance: float) -> dict[str, Any]:
    """Buffer all geometries by distance (CRS units; degrees for WGS84)."""
    return gis_ops.buffer_geometries(geojson, distance)


@server.tool()
def union_geometries(geojson: dict[str, Any]) -> dict[str, Any]:
    """Union all geometries into a single geometry (one feature out)."""
    return gis_ops.union_geometries(geojson)


@server.tool()
def intersection(geojson_a: dict[str, Any], geojson_b: dict[str, Any]) -> dict[str, Any]:
    """Intersection of the unions of two FeatureCollections."""
    return gis_ops.intersection(geojson_a, geojson_b)


@server.tool()
def difference(geojson_a: dict[str, Any], geojson_b: dict[str, Any]) -> dict[str, Any]:
    """Geometries of A minus B (single unioned feature out)."""
    return gis_ops.difference(geojson_a, geojson_b)


@server.tool()
def centroid(geojson: dict[str, Any]) -> dict[str, Any]:
    """Area-weighted centroid of each geometry; preserves properties."""
    return gis_ops.centroid(geojson)


@server.tool()
def representative_point(geojson: dict[str, Any]) -> dict[str, Any]:
    """Interior point inside each geometry; preserves properties; RFC 7946 order."""
    return gis_ops.representative_point(geojson)


@server.tool()
def area(geojson: dict[str, Any]) -> dict[str, Any]:
    """Area per feature and total; geodesic m^2 for geographic input, else CRS units."""
    return gis_ops.area(geojson)


@server.tool()
def reproject(geojson: dict[str, Any], from_crs: str, to_crs: str) -> dict[str, Any]:
    """Reproject a FeatureCollection, e.g. from_crs='EPSG:4326' to_crs='EPSG:2180'."""
    return gis_ops.reproject(geojson, from_crs, to_crs)


@server.tool()
def spatial_join_intersects(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Inner join on intersects; right props prefixed right_."""
    return gis_ops.spatial_join_intersects(left, right)


@server.tool()
def relate_de9im(geojson_a: dict[str, Any], geojson_b: dict[str, Any]) -> dict[str, Any]:
    """DE-9IM relation matrix and name between the unions of A and B (e.g. touches)."""
    return gis_ops.relate_de9im(geojson_a, geojson_b)


@server.tool()
def jenks_breaks(values: list[float], class_count: int = 4) -> dict[str, Any]:
    """Fisher-Jenks natural breaks: upper class bounds and class per input value."""
    return gis_ops.jenks_breaks(values, class_count)


@server.tool()
def nearest_feature(point: list[float], geojson: dict[str, Any]) -> dict[str, Any]:
    """Nearest feature to point [x, y] with distance in CRS units."""
    return gis_ops.nearest_feature(point, geojson)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
