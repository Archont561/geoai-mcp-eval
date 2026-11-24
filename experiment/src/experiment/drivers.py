"""Driver implementations for the prototype cells (scripted and Ollama).

Never a study result: scripted replays a deterministic canned plan to prove the
pipeline; Ollama talks to a local OpenAI-compatible endpoint. Outputs are
always labelled ``prototype``.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import requests
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from experiment import backends, mcp_client
from experiment.adapters.llm_cache import CompletionCache
from experiment.domain.cache_key import CacheKeySpec, build_cache_key
from experiment.domain.usage import (
    ABORT_REASON_TOKEN_CAP,
    TokenCapExceededError,
    UsageSnapshot,
    extract_response_usage,
)
from experiment.harness import (
    _K_CONTENT,
    _K_ID,
    _K_ROLE,
    RESULT_GEOJSON,
    RESULT_JSON,
    CellRequest,
    append_transcript,
    fixture_fc,
    run_python_sandboxed,
    stage_fixture_input,
    write_deliverable,
)

_MAX_TOOL_STEPS = 12
_TOOL_RESULT_CAP = 6000
_TRANSCRIPT_USER_CAP = 4000


@dataclass(frozen=True)
class _DriverSession:
    """Bundled cell request, validated backend profile, and live HTTP session."""

    req: CellRequest
    session: requests.Session
    profile: backends.BackendProfile


def _post_chat(
    session: requests.Session,
    profile: backends.BackendProfile,
    body: dict[str, Any],
) -> requests.Response:
    try:
        return session.post(profile.chat_url, json=body, timeout=profile.timeout)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
        raise backends.BackendError(
            "connection", f"cannot reach {profile.base_url}: {exc}"
        ) from exc
    except requests.exceptions.ReadTimeout as exc:
        msg = f"no response within {profile.read_timeout_s}s from {profile.base_url}"
        raise backends.BackendError("timeout", msg) from exc
    except requests.exceptions.RequestException as exc:
        raise backends.BackendError("transport", f"{exc.__class__.__name__}: {exc}") from exc


def _parse_chat_response(
    resp: requests.Response, profile: backends.BackendProfile
) -> dict[str, Any]:
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unspecified")
        detail = f"HTTP 429 after {profile.retries} retries (Retry-After: {retry_after})"
        raise backends.BackendError("rate-limit", detail)
    if resp.status_code >= 400:
        raise backends.BackendError(f"http-{resp.status_code}", resp.text[:300])
    try:
        return resp.json()
    except ValueError as exc:
        raise backends.BackendError(
            "invalid-response", f"response is not JSON: {resp.text[:300]}"
        ) from exc


def _chat_completions(
    session: requests.Session,
    profile: backends.BackendProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": profile.model,
        "messages": messages,
        "stream": False,
        "temperature": profile.temperature,
        "max_tokens": profile.max_tokens,
    }
    if tools:
        body["tools"] = tools
    resp = _post_chat(session, profile, body)
    return _parse_chat_response(resp, profile)


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


def _record_completion_usage(req: CellRequest, reply: dict[str, Any]) -> UsageSnapshot:
    snapshot = extract_response_usage(reply)
    if req.usage is not None:
        req.usage.record(snapshot)
    return snapshot


def _emit_usage_events(req: CellRequest, snapshot: UsageSnapshot) -> None:
    if snapshot.warning:
        append_transcript(
            req.cell,
            {
                _K_ROLE: "harness",
                "event": "usage_warning",
                "warning": snapshot.warning,
                _K_CONTENT: f"usage warning: {snapshot.warning}",
            },
        )
    if req.usage is not None and req.usage.cap_exceeded and req.usage.max_cell_tokens is not None:
        tokens_used = req.usage.observed_total_tokens
        cap = req.usage.max_cell_tokens
        append_transcript(
            req.cell,
            {
                _K_ROLE: "harness",
                "event": ABORT_REASON_TOKEN_CAP,
                "reason": ABORT_REASON_TOKEN_CAP,
                "tokens_used": tokens_used,
                "max_cell_tokens": cap,
                _K_CONTENT: f"{ABORT_REASON_TOKEN_CAP}: {tokens_used} > {cap}",
            },
        )
        raise TokenCapExceededError(tokens_used=tokens_used, max_cell_tokens=cap)


def _prepare_cache(
    ctx: _DriverSession,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[CompletionCache | None, str | None]:
    if not (ctx.req.use_cache and ctx.req.model_digest):
        return None, None
    key = build_cache_key(
        CacheKeySpec(
            backend_id=ctx.req.backend_id,
            model_digest=ctx.req.model_digest,
            messages=messages,
            tools=tools,
            temperature=ctx.profile.temperature,
            max_tokens=ctx.profile.max_tokens,
        )
    )
    return CompletionCache(ctx.req.cache_dir), key


def _cached_chat_completions(
    ctx: _DriverSession,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Call the LLM endpoint, using the digest-keyed disk cache when eligible."""
    cache, key = _prepare_cache(ctx, messages, tools)
    if cache is not None and key is not None:
        cached = cache.get(key)
        if cached is not None:
            if ctx.req.cache_stats is not None:
                ctx.req.cache_stats.record(hit=True)
            return cached, True
    reply = _chat_completions(ctx.session, ctx.profile, messages, tools)
    if cache is not None and key is not None:
        cache.put(key, reply)
    if ctx.req.cache_stats is not None:
        ctx.req.cache_stats.record(hit=False)
    return reply, False


def _tool_reply(
    ctx: _DriverSession,
    messages: list[dict[str, Any]],
    tool_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    reply, cache_hit = _cached_chat_completions(ctx, messages, tool_specs)
    snapshot = _record_completion_usage(ctx.req, reply)
    message = reply["choices"][0]["message"]
    messages.append(message)
    entry: dict[str, Any] = {
        _K_ROLE: "assistant",
        _K_CONTENT: message.get(_K_CONTENT),
        "tool_calls": message.get("tool_calls") or [],
        "cache_hit": cache_hit,
        "usage": snapshot.to_transcript_usage(),
    }
    if snapshot.warning:
        entry["usage_warning"] = snapshot.warning
    append_transcript(ctx.req.cell, entry)
    _emit_usage_events(ctx.req, snapshot)
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
    write_deliverable(req.cell, req.task, payload)


def _open_driver_session(req: CellRequest) -> _DriverSession:
    profile = req.profile or backends.fallback_profile(req.host, req.model)
    return _DriverSession(req=req, session=backends.build_session(profile), profile=profile)


def ollama_arm_a(req: CellRequest) -> None:
    ctx = _open_driver_session(req)
    try:
        return _ollama_arm_a(ctx)
    finally:
        ctx.session.close()


def _ollama_arm_a(ctx: _DriverSession) -> None:
    req = ctx.req
    fixture = fixture_fc(req.task_path, req.task)
    tool_specs, _ = asyncio.run(_mcp_tool_specs())
    system = (
        "You solve one GIS task with the provided tools only. Never invent data; the "
        "fixture is the only allowed input. When finished, reply with ONLY the final "
        f"deliverable as a single JSON code block ({RESULT_JSON}) or a raw GeoJSON object "
        f"({RESULT_GEOJSON}), no prose."
    )
    user = f"{req.task.prompt}\n\nFixture file ({req.task.fixture_input}):\n{json.dumps(fixture)}"
    messages = _initial_messages(req, system, user)
    for _step in range(_MAX_TOOL_STEPS):
        message = _tool_reply(ctx, messages, tool_specs)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            break
        messages.extend(_run_tool_call(req, call) for call in tool_calls)
    _deliver_json(req, messages[-1].get(_K_CONTENT) or "")


_ARM_B_SYSTEM = (
    "You solve one GIS task by writing a Python script. Use only the standard "
    "library plus geopandas/shapely/pyproj. The fixture is available as "
    "'input.geojson' in the working directory. Reply with ONLY a single "
    "```python fenced code block containing the complete script; no prose and "
    f"no other fences. The script must print the deliverable ({RESULT_JSON} or "
    f"{RESULT_GEOJSON}) as a single JSON object to stdout and nothing else."
)


def ollama_arm_b(req: CellRequest) -> None:
    ctx = _open_driver_session(req)
    try:
        return _ollama_arm_b(ctx)
    finally:
        ctx.session.close()


def _execute_arm_b_reply(req: CellRequest, content: str) -> None:
    # Only ```/```py/```python fences are code; a bare language tag (e.g. ```json)
    # must not leak into the captured source and get executed as Python.
    blocks = re.findall(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
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


def _ollama_arm_b(ctx: _DriverSession) -> None:
    req = ctx.req
    fixture_text = json.dumps(fixture_fc(req.task_path, req.task))
    stage_fixture_input(req.task_path, req.task, req.cell)
    user = (
        f"{req.task.prompt}\n\nFixture head (input.geojson, {len(fixture_text)} bytes):\n"
        f"{fixture_text[:_TOOL_RESULT_CAP]}"
    )
    messages = _initial_messages(req, _ARM_B_SYSTEM, user)
    reply, cache_hit = _cached_chat_completions(ctx, messages, None)
    snapshot = _record_completion_usage(req, reply)
    content = reply["choices"][0]["message"].get(_K_CONTENT) or ""
    entry: dict[str, Any] = {
        _K_ROLE: "assistant",
        _K_CONTENT: content,
        "cache_hit": cache_hit,
        "usage": snapshot.to_transcript_usage(),
    }
    if snapshot.warning:
        entry["usage_warning"] = snapshot.warning
    append_transcript(req.cell, entry)
    _emit_usage_events(req, snapshot)
    _execute_arm_b_reply(req, content)


def _deliver_stdout_json(req: CellRequest, stdout: str) -> None:
    payload = _extract_json_block(f"```json\n{stdout[-20000:]}\n```") or _extract_json_block(stdout)
    if payload is not None:
        write_deliverable(req.cell, req.task, payload)
