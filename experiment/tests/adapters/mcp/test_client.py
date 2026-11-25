"""Unit tests for ``experiment.adapters.mcp.client``."""

from __future__ import annotations

import asyncio

import pytest

from experiment.adapters.mcp import client as mcp_client
from experiment.adapters.mcp.client import McpToolSession


def test_call_tool_unknown_tool_returns_message() -> None:
    result = asyncio.run(mcp_client.call_tool("bogus_tool", {}))
    assert "bogus_tool" in str(result)


def test_persistent_mcp_tool_session_reuses_single_server() -> None:
    unopened = McpToolSession()
    with pytest.raises(RuntimeError, match="not open"):
        unopened.list_tool_specs()

    with McpToolSession() as session:
        specs = session.list_tool_specs()
        names = {spec["function"]["name"] for spec in specs}
        assert {"feature_info", "relate_de9im", "jenks_breaks"} <= names
        res1 = session.call_tool("jenks_breaks", {"values": [1, 2, 10, 11], "class_count": 2})
        res2 = session.call_tool("jenks_breaks", {"values": [1, 2, 10, 11], "class_count": 2})
        assert res1 == res2
        assert len(res1["breaks"]) == 2
