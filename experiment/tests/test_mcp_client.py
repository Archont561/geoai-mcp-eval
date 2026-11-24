"""Defensive stdio MCP client behavior not exposed by the CLI self-test."""

from __future__ import annotations

from experiment.adapters.mcp import client as mcp_client


def test_call_tool_unknown_tool_returns_message() -> None:
    import asyncio

    # The server answers unknown tool names with a plain-text message rather
    # than a protocol error; call_tool surfaces that payload.
    result = asyncio.run(mcp_client.call_tool("bogus_tool", {}))
    assert "bogus_tool" in str(result)
