"""Ollama Python SDK chat completion gateway (``ollama.Client.chat``)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import ollama
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from experiment.adapters import backends
from experiment.adapters import ollama as ollama_adapter
from experiment.domain.backend import BackendError, BackendProfile
from experiment.domain.prompts import ChatTurn

_RETRYABLE_STATUSES = ollama_adapter.RETRYABLE_STATUSES


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_args_dict(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, Mapping):
        return dict(raw_args)
    return _parse_json_object(raw_args) if isinstance(raw_args, str) else {}


def _normalize_outgoing_tool_calls(raw_calls: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for call in raw_calls:
        if not isinstance(call, Mapping):
            continue
        func = call.get("function") if isinstance(call.get("function"), Mapping) else {}
        normalized.append(
            {
                "function": {
                    "name": str(func.get("name") or ""),
                    "arguments": _parse_args_dict(func.get("arguments")),
                }
            }
        )
    return normalized


def normalize_messages_for_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate OpenAI-style chat history into ``ollama.Client.chat()`` messages."""
    converted: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {
            "role": str(msg.get("role") or "user"),
            "content": "" if msg.get("content") is None else str(msg["content"]),
        }
        if msg.get("tool_calls"):
            entry["tool_calls"] = _normalize_outgoing_tool_calls(list(msg["tool_calls"]))
        if msg.get("name"):
            entry["tool_name"] = str(msg["name"])
        converted.append(entry)
    return converted


def _normalize_incoming_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_calls, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, call in enumerate(raw_calls, start=1):
        call_dict = ollama_adapter.as_mapping(call)
        func = ollama_adapter.as_mapping(call_dict.get("function"))
        name = str(func.get("name") or "")
        args = func.get("arguments")
        raw_args = args if isinstance(args, str) else json.dumps(args or {}, sort_keys=True)
        out.append(
            {
                "id": str(call_dict.get("id") or f"call_{idx}_{name}"),
                "type": "function",
                "function": {"name": name, "arguments": raw_args},
            }
        )
    return out


def _is_exact_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _extract_usage(raw: Mapping[str, Any]) -> dict[str, int] | None:
    prompt_tokens = raw.get("prompt_eval_count")
    completion_tokens = raw.get("eval_count")
    has_prompt = _is_exact_int(prompt_tokens)
    has_completion = _is_exact_int(completion_tokens)
    if not has_prompt and not has_completion:
        return None
    usage: dict[str, int] = {}
    if has_prompt:
        usage["prompt_tokens"] = prompt_tokens
    if has_completion:
        usage["completion_tokens"] = completion_tokens
    if has_prompt and has_completion:
        usage["total_tokens"] = prompt_tokens + completion_tokens
    return usage


def normalize_ollama_chat_response(response: Any) -> dict[str, Any]:
    """Translate an ``ollama.ChatResponse`` into the canonical OpenAI-style dict."""
    raw = ollama_adapter.as_mapping(response)
    raw_msg = ollama_adapter.as_mapping(raw.get("message"))
    message: dict[str, Any] = {
        "role": str(raw_msg.get("role") or "assistant"),
        "content": raw_msg.get("content"),
    }
    tool_calls = _normalize_incoming_tool_calls(raw_msg.get("tool_calls"))
    if tool_calls:
        message["tool_calls"] = tool_calls
    payload: dict[str, Any] = {
        "choices": [{"message": message, "finish_reason": raw.get("done_reason") or "stop"}]
    }
    usage = _extract_usage(raw)
    if usage is not None:
        payload["usage"] = usage
    return payload


def _translate_transport_error(exc: Exception, profile: BackendProfile) -> BackendError:
    if isinstance(exc, httpx.TimeoutException):
        return BackendError(
            "timeout", f"no response within {profile.read_timeout_s}s from {profile.base_url}"
        )
    if isinstance(exc, httpx.ConnectError | ConnectionError | OSError):
        return BackendError("connection", f"cannot reach {profile.base_url}: {exc}")
    return BackendError("transport", f"{exc.__class__.__name__}: {exc}")


def _translate_ollama_error(exc: Exception, profile: BackendProfile) -> BackendError:
    if isinstance(exc, ollama.ResponseError):
        status = int(exc.status_code)
        detail = str(exc.error or exc)[:300]
        if status == 429:
            return BackendError("rate-limit", f"HTTP 429 after {profile.retries} retries: {detail}")
        return BackendError(f"http-{status}", detail)
    return _translate_transport_error(exc, profile)


def _send_ollama_chat(
    active: Any,
    profile: BackendProfile,
    ollama_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    options = {"temperature": profile.temperature, "num_predict": profile.max_tokens}
    response = active.chat(
        model=profile.model,
        messages=ollama_messages,
        tools=tools or None,
        stream=False,
        options=options,
    )
    return normalize_ollama_chat_response(response)


def _is_retryable_ollama_error(exc: BaseException) -> bool:
    return isinstance(exc, ollama.ResponseError) and int(exc.status_code) in _RETRYABLE_STATUSES


def chat_completions_sdk(
    profile: BackendProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    client: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute one chat turn through ``ollama.Client.chat()`` with ``tenacity`` 429/5xx retries."""
    timeout = httpx.Timeout(profile.read_timeout_s, connect=profile.connect_timeout_s)
    active = (
        client
        if client is not None
        else ollama_adapter.build_client(profile.api_root, timeout=timeout)
    )
    ollama_messages = normalize_messages_for_ollama(messages)
    retrying = Retrying(
        stop=stop_after_attempt(profile.retries + 1),
        wait=wait_exponential(multiplier=ollama_adapter.DEFAULT_RETRY_BACKOFF_S, exp_base=2),
        retry=retry_if_exception(_is_retryable_ollama_error),
        reraise=True,
        sleep=sleep,
    )
    try:
        return retrying(_send_ollama_chat, active, profile, ollama_messages, tools)
    except (ollama.ResponseError, ollama.RequestError, httpx.HTTPError, OSError) as exc:
        raise _translate_ollama_error(exc, profile) from exc


class OllamaChatGateway:
    """``ChatGateway`` backed by the official ``ollama.Client`` SDK."""

    def __init__(self, profile: BackendProfile, *, client: Any | None = None) -> None:
        self._profile = profile
        timeout = httpx.Timeout(profile.read_timeout_s, connect=profile.connect_timeout_s)
        self._client = (
            client
            if client is not None
            else ollama_adapter.build_client(profile.api_root, timeout=timeout)
        )

    @property
    def temperature(self) -> float:
        return self._profile.temperature

    @property
    def max_tokens(self) -> int:
        return self._profile.max_tokens

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return chat_completions_sdk(self._profile, messages, tools, client=self._client)

    def parse_turn(self, reply: dict[str, Any]) -> ChatTurn:
        return backends.parse_chat_turn(reply)

    def close(self) -> None:
        inner = getattr(self._client, "_client", None)
        if inner is not None and hasattr(inner, "close"):
            inner.close()
