"""Live LLM runner over injected Clean Architecture ports.

Arm A (Typed MCP) runs a multi-turn tool-calling loop over a persistent MCP
session; Arm B (Codegen) requests a Python script and executes it in an
isolated sandbox. Transport, wire translation, MCP stdio, and disk I/O live
in ``experiment.adapters``; prompts and parsers live in ``experiment.domain``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiment.adapters import backends
from experiment.adapters.harness_io import (
    FilesystemCellWorkspace,
    SubprocessCodeSandbox,
    create_chat_gateway,
)
from experiment.adapters.llm_cache import CompletionCache
from experiment.adapters.mcp.client import McpToolSession
from experiment.domain.cache_key import CacheKeySpec, build_cache_key
from experiment.domain.prompts import (
    ARM_A_SYSTEM_PROMPT,
    ARM_B_SYSTEM_PROMPT,
    MSG_CONTENT,
    MSG_ROLE,
    ChatTurn,
    ToolCall,
    extract_json_block,
    extract_python_code_block,
    extract_stdout_json,
)
from experiment.domain.usage import (
    ABORT_REASON_TOKEN_CAP,
    TokenCapExceededError,
    UsageSnapshot,
    extract_response_usage,
)
from experiment.services.runners.ports import (
    CompletionCachePort,
    HarnessPorts,
    ToolSession,
    TrialRequest,
)

_MAX_TOOL_STEPS = 8
_TOOL_RESULT_CAP = 12000
_TRANSCRIPT_USER_CAP = 2000


# Kept as dataclass (not BaseModel): binds TrialRequest with non-serializable HarnessPorts.
@dataclass(frozen=True)
class _CellContext:
    """Bundled request and injected ports for executing one trial."""

    req: TrialRequest
    ports: HarnessPorts


def _build_default_ports(req: TrialRequest) -> HarnessPorts:
    profile = req.profile or backends.fallback_profile(req.host, req.model)
    cache: CompletionCachePort | None = (
        CompletionCache(req.cache_dir) if (req.use_cache and req.model_digest) else None
    )
    return HarnessPorts(
        chat=create_chat_gateway(profile),
        open_tools=McpToolSession,
        sandbox=SubprocessCodeSandbox(),
        workspace=FilesystemCellWorkspace(),
        cache=cache,
    )


def _initial_messages(ctx: _CellContext, system: str, user: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {MSG_ROLE: "system", MSG_CONTENT: system},
        {MSG_ROLE: "user", MSG_CONTENT: user},
    ]
    ctx.ports.workspace.append_transcript(ctx.req.cell, {MSG_ROLE: "system", MSG_CONTENT: system})
    ctx.ports.workspace.append_transcript(
        ctx.req.cell, {MSG_ROLE: "user", MSG_CONTENT: user[:_TRANSCRIPT_USER_CAP]}
    )
    return messages


def _record_completion_usage(req: TrialRequest, reply: dict[str, Any]) -> UsageSnapshot:
    snapshot = extract_response_usage(reply)
    if req.usage is not None:
        req.usage.record(snapshot)
    return snapshot


def _emit_usage_events(ctx: _CellContext, snapshot: UsageSnapshot) -> None:
    req = ctx.req
    workspace = ctx.ports.workspace
    if snapshot.warning:
        workspace.append_transcript(
            req.cell,
            {
                MSG_ROLE: "harness",
                "event": "usage_warning",
                "warning": snapshot.warning,
                MSG_CONTENT: f"usage warning: {snapshot.warning}",
            },
        )
    if req.usage is not None and req.usage.cap_exceeded and req.usage.max_cell_tokens is not None:
        tokens_used = req.usage.observed_total_tokens
        cap = req.usage.max_cell_tokens
        workspace.append_transcript(
            req.cell,
            {
                MSG_ROLE: "harness",
                "event": ABORT_REASON_TOKEN_CAP,
                "reason": ABORT_REASON_TOKEN_CAP,
                "tokens_used": tokens_used,
                "max_cell_tokens": cap,
                MSG_CONTENT: f"{ABORT_REASON_TOKEN_CAP}: {tokens_used} > {cap}",
            },
        )
        raise TokenCapExceededError(tokens_used=tokens_used, max_cell_tokens=cap)


def _cache_key(
    ctx: _CellContext,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> str | None:
    if ctx.ports.cache is None or not ctx.req.model_digest:
        return None
    return build_cache_key(
        CacheKeySpec(
            backend_id=ctx.req.backend_id,
            model_digest=ctx.req.model_digest,
            messages=messages,
            tools=tools,
            temperature=ctx.ports.chat.temperature,
            max_tokens=ctx.ports.chat.max_tokens,
        )
    )


def _cached_complete(
    ctx: _CellContext,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], ChatTurn, bool]:
    """Call the chat gateway, consulting the digest-keyed cache when configured."""
    key = _cache_key(ctx, messages, tools)
    cache = ctx.ports.cache
    if cache is not None and key is not None:
        cached = cache.get(key)
        if cached is not None:
            if ctx.req.cache_stats is not None:
                ctx.req.cache_stats.record(hit=True)
            return cached, ctx.ports.chat.parse_turn(cached), True
    reply = ctx.ports.chat.complete(messages, tools)
    if cache is not None and key is not None:
        cache.put(key, reply)
    if ctx.req.cache_stats is not None:
        ctx.req.cache_stats.record(hit=False)
    return reply, ctx.ports.chat.parse_turn(reply), False


def _tool_reply(
    ctx: _CellContext,
    messages: list[dict[str, Any]],
    tool_specs: list[dict[str, Any]],
) -> ChatTurn:
    reply, turn, cache_hit = _cached_complete(ctx, messages, tool_specs)
    snapshot = _record_completion_usage(ctx.req, reply)
    messages.append(turn.raw_message)
    entry: dict[str, Any] = {
        MSG_ROLE: "assistant",
        MSG_CONTENT: turn.content,
        "tool_calls": turn.raw_message.get("tool_calls") or [],
        "cache_hit": cache_hit,
        "usage": snapshot.to_transcript_usage(),
    }
    if snapshot.warning:
        entry["usage_warning"] = snapshot.warning
    ctx.ports.workspace.append_transcript(ctx.req.cell, entry)
    _emit_usage_events(ctx, snapshot)
    return turn


def _run_tool_call(ctx: _CellContext, tools: ToolSession, call: ToolCall) -> dict[str, Any]:
    try:
        result: Any = tools.call_tool(call.name, call.arguments)
    except Exception as exc:
        result = {"error": str(exc)}
    ctx.ports.workspace.append_transcript(
        ctx.req.cell, {MSG_ROLE: "tool", "name": call.name, MSG_CONTENT: result}
    )
    return {
        MSG_ROLE: "tool",
        "tool_call_id": call.call_id,
        "name": call.name,
        MSG_CONTENT: json.dumps(result, default=str)[:_TOOL_RESULT_CAP],
    }


def _deliver_json(ctx: _CellContext, final: str) -> None:
    payload = extract_json_block(final)
    if payload is None:
        ctx.ports.workspace.append_transcript(
            ctx.req.cell, {MSG_ROLE: "harness", MSG_CONTENT: "no JSON deliverable extracted"}
        )
        return
    ctx.ports.workspace.write_deliverable(ctx.req.cell, ctx.req.task, payload)


def _run_arm_a(ctx: _CellContext) -> None:
    req = ctx.req
    fixture = ctx.ports.workspace.load_fixture(req.task_path, req.task)
    user = f"{req.task.prompt}\n\nFixture file ({req.task.fixture_input}):\n{json.dumps(fixture)}"
    with ctx.ports.open_tools() as tools:
        tool_specs = tools.list_tool_specs()
        messages = _initial_messages(ctx, ARM_A_SYSTEM_PROMPT, user)
        last_turn: ChatTurn | None = None
        for _step in range(_MAX_TOOL_STEPS):
            last_turn = _tool_reply(ctx, messages, tool_specs)
            if not last_turn.tool_calls:
                break
            messages.extend(_run_tool_call(ctx, tools, call) for call in last_turn.tool_calls)
    _deliver_json(ctx, (last_turn.content if last_turn is not None else "") or "")


def _execute_arm_b_reply(ctx: _CellContext, content: str, fixture_src: Path) -> None:
    code = extract_python_code_block(content)
    if code is None:
        ctx.ports.workspace.append_transcript(
            ctx.req.cell, {MSG_ROLE: "harness", MSG_CONTENT: "no python block found"}
        )
        return
    completed = ctx.ports.sandbox.execute(code, fixture_src=fixture_src)
    ctx.ports.workspace.append_transcript(
        ctx.req.cell,
        {
            MSG_ROLE: "tool_result",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        },
    )
    payload = extract_stdout_json(completed.stdout)
    if payload is not None:
        ctx.ports.workspace.write_deliverable(ctx.req.cell, ctx.req.task, payload)


def _arm_b_user_prompt(ctx: _CellContext) -> str:
    fixture_text = json.dumps(ctx.ports.workspace.load_fixture(ctx.req.task_path, ctx.req.task))
    return (
        f"{ctx.req.task.prompt}\n\nFixture head (input.geojson, {len(fixture_text)} bytes):\n"
        f"{fixture_text[:_TOOL_RESULT_CAP]}"
    )


def _run_arm_b(ctx: _CellContext) -> None:
    req = ctx.req
    fixture_src = ctx.ports.workspace.resolve_fixture(req.task_path, req.task)
    messages = _initial_messages(ctx, ARM_B_SYSTEM_PROMPT, _arm_b_user_prompt(ctx))
    reply, turn, cache_hit = _cached_complete(ctx, messages, None)
    snapshot = _record_completion_usage(req, reply)
    content = turn.content or ""
    entry: dict[str, Any] = {
        MSG_ROLE: "assistant",
        MSG_CONTENT: content,
        "cache_hit": cache_hit,
        "usage": snapshot.to_transcript_usage(),
    }
    if snapshot.warning:
        entry["usage_warning"] = snapshot.warning
    ctx.ports.workspace.append_transcript(req.cell, entry)
    _emit_usage_events(ctx, snapshot)
    _execute_arm_b_reply(ctx, content, fixture_src)


def ollama_arm_a(req: TrialRequest, *, ports: HarnessPorts | None = None) -> None:
    """Execute one Arm A (Typed MCP) trial over live or injected ports."""
    active_ports = ports if ports is not None else _build_default_ports(req)
    try:
        _run_arm_a(_CellContext(req=req, ports=active_ports))
    finally:
        if ports is None:
            active_ports.chat.close()


def ollama_arm_b(req: TrialRequest, *, ports: HarnessPorts | None = None) -> None:
    """Execute one Arm B (Codegen) trial over live or injected ports."""
    active_ports = ports if ports is not None else _build_default_ports(req)
    try:
        _run_arm_b(_CellContext(req=req, ports=active_ports))
    finally:
        if ports is None:
            active_ports.chat.close()
