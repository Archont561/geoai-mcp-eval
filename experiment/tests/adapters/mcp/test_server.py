"""Unit tests for ``experiment.adapters.mcp.server``."""

from __future__ import annotations

import asyncio

from experiment import gis_ops
from experiment.adapters.mcp import server as mcp_server


def test_mcp_server_exposes_exactly_the_ops_registry() -> None:
    tools = asyncio.run(mcp_server.server.list_tools())
    assert {t.name for t in tools} == set(gis_ops.OPS)
