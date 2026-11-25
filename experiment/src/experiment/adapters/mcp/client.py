"""Stdio MCP client helpers and persistent single-process session for Arm A."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import threading
from types import TracebackType
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from experiment.adapters.paths import package_src_root

_SessionRequest = tuple[str | None, Any, concurrent.futures.Future[Any] | None]


def server_params() -> StdioServerParameters:
    """Run the GIS prototype server from this interpreter (absolute PYTHONPATH)."""
    src_root = str(package_src_root())
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing}" if existing else src_root
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "experiment.adapters.mcp.server"],
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


def _openai_tool_from_mcp(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or "").strip(),
            "parameters": schema,
        },
    }


async def _invoke_on_session(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    result = await session.call_tool(name, arguments)
    if getattr(result, "isError", False):
        raise RuntimeError(f"tool {name} failed: {result}")
    return _parse_result(result)


async def _specs_on_session(session: ClientSession) -> list[dict[str, Any]]:
    result = await session.list_tools()
    return [_openai_tool_from_mcp(tool) for tool in result.tools]


async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    async with (
        stdio_client(server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await _invoke_on_session(session, name, arguments)


async def list_tools() -> list[str]:
    async with (
        stdio_client(server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [tool.name for tool in result.tools]


async def list_tool_specs() -> tuple[list[dict[str, Any]], list[Any]]:
    """Return OpenAI function-calling specs alongside raw MCP tool descriptors."""
    async with (
        stdio_client(server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [_openai_tool_from_mcp(tool) for tool in result.tools], list(result.tools)


class McpToolSession:
    """Synchronous context manager reusing one stdio MCP server process across calls."""

    def __init__(self, params: StdioServerParameters | None = None) -> None:
        self._params = params if params is not None else server_params()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[_SessionRequest] | None = None
        self._ready: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._thread: threading.Thread | None = None

    async def _dispatch_request(self, session: ClientSession, action: str, payload: Any) -> Any:
        if action == "list_specs":
            return await _specs_on_session(session)
        if action == "call_tool":
            name, arguments = payload
            return await _invoke_on_session(session, name, arguments)
        raise ValueError(f"unknown MCP session action: {action!r}")

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        try:
            async with (
                stdio_client(self._params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                self._ready.set_result(None)
                await self._drain_queue(session)
        except Exception as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)

    async def _drain_queue(self, session: ClientSession) -> None:
        assert self._queue is not None
        while True:
            action, payload, future = await self._queue.get()
            if action is None:
                return
            assert future is not None
            try:
                value = await self._dispatch_request(session, action, payload)
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(value)

    def _submit(self, action: str, payload: Any = None) -> Any:
        if self._loop is None or self._queue is None:
            raise RuntimeError("McpToolSession is not open")
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (action, payload, future))
        return future.result()

    def list_tool_specs(self) -> list[dict[str, Any]]:
        """Return OpenAI function-calling specs from the active MCP server."""
        return list(self._submit("list_specs"))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke one tool on the active MCP server."""
        return self._submit("call_tool", (name, arguments))

    def close(self) -> None:
        """Shut down the background event loop and stdio MCP subprocess."""
        if self._loop is not None and self._queue is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (None, None, None))
        if self._thread is not None:
            self._thread.join(timeout=15)
            self._thread = None

    def __enter__(self) -> McpToolSession:
        self._thread = threading.Thread(target=lambda: asyncio.run(self._serve()), daemon=True)
        self._thread.start()
        self._ready.result(timeout=30)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.close()
