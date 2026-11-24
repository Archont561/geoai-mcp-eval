"""Exercise the GIS MCP server with the shipped topology fixture."""

from __future__ import annotations

from experiment.adapters import run_store
from experiment.adapters.harness_io import TASK_ROOT
from experiment.adapters.mcp import client as mcp_client


async def selftest_rows() -> list[tuple[str, str, str]]:
    """List tools, filter the two countries, and check their boundary relation."""
    tools = await mcp_client.list_tools()
    fixture = TASK_ROOT / "fixtures" / "analysis" / "poland-czechia.geojson"
    payload = run_store.read_json(fixture)
    pol = await mcp_client.call_tool(
        "filter_features", {"geojson": payload, "property": "ISO_A3", "equals": "POL"}
    )
    cze = await mcp_client.call_tool(
        "filter_features", {"geojson": payload, "property": "ISO_A3", "equals": "CZE"}
    )
    de9im = await mcp_client.call_tool("relate_de9im", {"geojson_a": pol, "geojson_b": cze})
    admin = str(pol["features"][0]["properties"].get("ADMIN"))
    return [
        ("list_tools", f"{len(tools)} tools", ", ".join(tools[:5]) + " …"),
        ("filter_features POL", f"{len(pol['features'])} feature", admin),
        ("relate_de9im POL×CZE", de9im["relation"], de9im["de9im"]),
    ]
