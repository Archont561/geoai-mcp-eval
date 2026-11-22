"""Integration tests for the stdio MCP client + server (14 tools)."""

from __future__ import annotations

import json
from pathlib import Path

from experiment import mcp_client

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tasks"
    / "fixtures"
    / "analysis"
    / "poland-czechia.geojson"
)


def test_list_tools_via_stdio() -> None:
    import asyncio

    tools = asyncio.run(mcp_client.list_tools())
    assert len(tools) == 14
    assert "relate_de9im" in tools


def test_call_tool_roundtrip() -> None:
    import asyncio

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = asyncio.run(
        mcp_client.call_tool(
            "filter_features", {"geojson": fixture, "property": "ISO_A3", "equals": "POL"}
        )
    )
    assert result["features"][0]["properties"]["ADMIN"] == "Poland"


def test_call_tool_unknown_tool_returns_message() -> None:
    import asyncio

    # The server answers unknown tool names with a plain-text message rather
    # than a protocol error; call_tool surfaces that payload.
    result = asyncio.run(mcp_client.call_tool("bogus_tool", {}))
    assert "bogus_tool" in str(result)
