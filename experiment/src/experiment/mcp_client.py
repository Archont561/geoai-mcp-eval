"""Stdio MCP client helpers for the prototype harness."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from experiment.adapters.paths import package_src_root


def server_params() -> StdioServerParameters:
    """Run the GIS prototype server from this interpreter (absolute PYTHONPATH)."""
    src_root = str(package_src_root())
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing}" if existing else src_root
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "experiment.mcp_server"],
        env=env,
    )


def _parse_result(result: Any) -> Any:
    """Pull a JSON-ish payload out of a CallToolResult."""
    contents = getattr(result, "content", None) or []
    for item in contents:
        text = getattr(item, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return getattr(result, "structuredContent", None)


async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    async with (
        stdio_client(server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        if getattr(result, "isError", False):
            raise RuntimeError(f"tool {name} failed: {result}")
        return _parse_result(result)


async def list_tools() -> list[str]:
    async with (
        stdio_client(server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [tool.name for tool in result.tools]
