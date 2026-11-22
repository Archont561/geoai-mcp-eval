"""Driver implementations for the prototype cells (scripted and Ollama).

Never a study result: scripted replays a deterministic canned plan to prove the
pipeline; Ollama talks to a local OpenAI-compatible endpoint. Outputs are
always labelled ``prototype``.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from experiment import mcp_client
from experiment.harness import (
    _K_CONTENT,
    _K_ID,
    _K_ROLE,
    JSON_INDENT,
    RESULT_GEOJSON,
    RESULT_JSON,
    UTF8,
    CellRequest,
    append_transcript,
    deliverable_name,
    fixture_fc,
    fixture_path,
    run_python_sandboxed,
)

_MAX_TOOL_STEPS = 12
_TOOL_RESULT_CAP = 6000
_TRANSCRIPT_USER_CAP = 4000


def _chat_completions(
    host: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    timeout_s: int = 240,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    if tools:
        body["tools"] = tools
    request = urllib.request.Request(
        f"{host.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


async def _mcp_tool_specs() -> tuple[list[dict[str, Any]], list[Any]]:
    async with (
        stdio_client(mcp_client.server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [_openai_tool_from_mcp(t) for t in result.tools], list(result.tools)


def _extract_json_block(text: str) -> Any | None:
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not candidates:
        brace = text.rfind("{")
        if brace == -1:
            return None
        candidates = [text[brace:]]
    for raw in reversed(candidates):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return None


def _initial_messages(req: CellRequest, system: str, user: str) -> list[dict[str, Any]]:
    messages = [{_K_ROLE: "system", _K_CONTENT: system}, {_K_ROLE: "user", _K_CONTENT: user}]
    append_transcript(req.cell, {_K_ROLE: "system", _K_CONTENT: system})
    append_transcript(req.cell, {_K_ROLE: "user", _K_CONTENT: user[:_TRANSCRIPT_USER_CAP]})
    return messages


def _tool_reply(
    req: CellRequest, messages: list[dict[str, Any]], tool_specs: list[dict[str, Any]]
) -> dict[str, Any]:
    reply = _chat_completions(req.host, req.model, messages, tool_specs)
    message = reply["choices"][0]["message"]
    messages.append(message)
    append_transcript(
        req.cell,
        {
            _K_ROLE: "assistant",
            _K_CONTENT: message.get(_K_CONTENT),
            "tool_calls": message.get("tool_calls") or [],
        },
    )
    return message


def _run_tool_call(req: CellRequest, call: dict[str, Any]) -> dict[str, Any]:
    name = call["function"]["name"]
    try:
        arguments = json.loads(call["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        arguments = {}
    try:
        result = asyncio.run(mcp_client.call_tool(name, arguments))
    except Exception as exc:
        result = {"error": str(exc)}
    append_transcript(req.cell, {_K_ROLE: "tool", "name": name, _K_CONTENT: result})
    return {
        _K_ROLE: "tool",
        "tool_call_id": call.get(_K_ID, name),
        "name": name,
        _K_CONTENT: json.dumps(result, default=str)[:_TOOL_RESULT_CAP],
    }


def _deliver_json(req: CellRequest, final: str) -> None:
    payload = _extract_json_block(final)
    if payload is None:
        append_transcript(
            req.cell, {_K_ROLE: "harness", _K_CONTENT: "no JSON deliverable extracted"}
        )
        return
    (req.cell / deliverable_name(req.task)).write_text(
        json.dumps(payload, indent=JSON_INDENT), encoding=UTF8
    )


def ollama_arm_a(req: CellRequest) -> None:
    fixture = fixture_fc(req.task_path, req.task)
    tool_specs, _ = asyncio.run(_mcp_tool_specs())
    system = (
        "You solve one GIS task with the provided tools only. Never invent data; the "
        "fixture is the only allowed input. When finished, reply with ONLY the final "
        f"deliverable as a single JSON code block ({RESULT_JSON}) or a raw GeoJSON object "
        f"({RESULT_GEOJSON}), no prose."
    )
    fixture_file = req.task["fixtures"]["input"]
    user = f"{req.task['prompt']}\n\nFixture file ({fixture_file}):\n{json.dumps(fixture)}"
    messages = _initial_messages(req, system, user)
    for _step in range(_MAX_TOOL_STEPS):
        message = _tool_reply(req, messages, tool_specs)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            break
        messages.extend(_run_tool_call(req, call) for call in tool_calls)
    _deliver_json(req, messages[-1].get(_K_CONTENT) or "")


_ARM_B_SYSTEM = (
    "You solve one GIS task by writing a Python script. Use only the standard "
    "library plus geopandas/shapely/pyproj. The fixture is available as "
    "'input.geojson' in the working directory. Print the deliverable "
    f"({RESULT_JSON} or {RESULT_GEOJSON}) as a single JSON object to stdout and nothing else."
)


def ollama_arm_b(req: CellRequest) -> None:
    fixture = fixture_fc(req.task_path, req.task)
    (req.cell / "input.geojson").write_bytes(fixture_path(req.task_path, req.task).read_bytes())
    system = _ARM_B_SYSTEM
    size = len(json.dumps(fixture))
    head = json.dumps(fixture)[:_TOOL_RESULT_CAP]
    user = f"{req.task['prompt']}\n\nFixture head (input.geojson, {size} bytes):\n{head}"
    messages = _initial_messages(req, system, user)
    reply = _chat_completions(req.host, req.model, messages, None)
    content = reply["choices"][0]["message"].get(_K_CONTENT) or ""
    append_transcript(req.cell, {_K_ROLE: "assistant", _K_CONTENT: content})
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", content, re.DOTALL)
    if not blocks:
        append_transcript(req.cell, {_K_ROLE: "harness", _K_CONTENT: "no python block found"})
        return
    completed = run_python_sandboxed(blocks[0], req.cell)
    append_transcript(
        req.cell,
        {
            _K_ROLE: "tool_result",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        },
    )
    _deliver_stdout_json(req, completed.stdout)


def _deliver_stdout_json(req: CellRequest, stdout: str) -> None:
    payload = _extract_json_block(f"```json\n{stdout[-20000:]}\n```") or _extract_json_block(stdout)
    if payload is not None:
        (req.cell / deliverable_name(req.task)).write_text(
            json.dumps(payload, indent=JSON_INDENT), encoding=UTF8
        )
