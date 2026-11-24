"""Exercise the GIS MCP server with the shipped topology fixture."""

from __future__ import annotations

import json

from experiment import mcp_client
from experiment.harness import TASK_ROOT


async def selftest_rows() -> list[tuple[str, str, str]]:
    """List tools, filter the two countries, and check their boundary relation."""
    tools = await mcp_client.list_tools()
    fixture = TASK_ROOT / "fixtures" / "analysis" / "poland-czechia.geojson"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
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
