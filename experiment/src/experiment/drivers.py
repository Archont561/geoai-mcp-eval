"""Driver implementations for the prototype cells (scripted and Ollama).

Never a study result: scripted replays a deterministic canned plan to prove the
pipeline; Ollama talks to a local OpenAI-compatible endpoint. Outputs are
always labelled ``prototype``.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import requests
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from experiment import backends, mcp_client
from experiment.adapters.llm_cache import CompletionCache
from experiment.domain.cache_key import build_cache_key
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
    try:
        resp = session.post(profile.chat_url, json=body, timeout=profile.timeout)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
        detail = f"cannot reach {profile.base_url}: {exc}"
        raise backends.BackendError("connection", detail) from exc
    except requests.exceptions.ReadTimeout as exc:
        raise backends.BackendError(
            "timeout", f"no response within {profile.read_timeout_s}s from {profile.base_url}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise backends.BackendError("transport", f"{exc.__class__.__name__}: {exc}") from exc
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unspecified")
        raise backends.BackendError(
            "rate-limit", f"HTTP 429 after {profile.retries} retries (Retry-After: {retry_after})"
        )
    if resp.status_code >= 400:
        raise backends.BackendError(f"http-{resp.status_code}", resp.text[:300])
    try:
        return resp.json()
    except ValueError as exc:
        detail = f"response is not JSON: {resp.text[:300]}"
        raise backends.BackendError("invalid-response", detail) from exc


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


def _cached_chat_completions(
    req: CellRequest,
    session: requests.Session,
    profile: backends.BackendProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Call the LLM endpoint, using the digest-keyed disk cache when eligible."""
    cache: CompletionCache | None = None
    key: str | None = None
    if req.use_cache and req.model_digest:
        key = build_cache_key(
            backend_id=req.backend_id,
            model_digest=req.model_digest,
            messages=messages,
            tools=tools,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        cache = CompletionCache(req.cache_dir)
        cached = cache.get(key)
        if cached is not None:
            if req.cache_stats is not None:
                req.cache_stats.record(hit=True)
            return cached, True
    reply = _chat_completions(session, profile, messages, tools)
    if cache is not None and key is not None:
        cache.put(key, reply)
    if req.cache_stats is not None:
        req.cache_stats.record(hit=False)
    return reply, False


def _tool_reply(
    req: CellRequest,
    messages: list[dict[str, Any]],
    tool_specs: list[dict[str, Any]],
    session: requests.Session,
    profile: backends.BackendProfile,
) -> dict[str, Any]:
    reply, cache_hit = _cached_chat_completions(req, session, profile, messages, tool_specs)
    snapshot = _record_completion_usage(req, reply)
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
    append_transcript(req.cell, entry)
    _emit_usage_events(req, snapshot)
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


def _profile_and_session(req: CellRequest) -> tuple[backends.BackendProfile, requests.Session]:
    profile = req.profile or backends.fallback_profile(req.host, req.model)
    return profile, backends.build_session(profile)


def ollama_arm_a(req: CellRequest) -> None:
    profile, session = _profile_and_session(req)
    try:
        return _ollama_arm_a(req, session, profile)
    finally:
        session.close()


def _ollama_arm_a(
    req: CellRequest, session: requests.Session, profile: backends.BackendProfile
) -> None:
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
        message = _tool_reply(req, messages, tool_specs, session, profile)
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
    profile, session = _profile_and_session(req)
    try:
        return _ollama_arm_b(req, session, profile)
    finally:
        session.close()


def _ollama_arm_b(
    req: CellRequest, session: requests.Session, profile: backends.BackendProfile
) -> None:
    fixture = fixture_fc(req.task_path, req.task)
    (req.cell / "input.geojson").write_bytes(fixture_path(req.task_path, req.task).read_bytes())
    system = _ARM_B_SYSTEM
    size = len(json.dumps(fixture))
    head = json.dumps(fixture)[:_TOOL_RESULT_CAP]
    user = f"{req.task.prompt}\n\nFixture head (input.geojson, {size} bytes):\n{head}"
    messages = _initial_messages(req, system, user)
    reply, cache_hit = _cached_chat_completions(req, session, profile, messages, None)
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


def _deliver_stdout_json(req: CellRequest, stdout: str) -> None:
    payload = _extract_json_block(f"```json\n{stdout[-20000:]}\n```") or _extract_json_block(stdout)
    if payload is not None:
        (req.cell / deliverable_name(req.task)).write_text(
            json.dumps(payload, indent=JSON_INDENT), encoding=UTF8
        )
