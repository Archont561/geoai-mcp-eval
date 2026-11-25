"""Official ``openrouter`` Python SDK adapters for ``ChatGateway`` and ``BackendProbe``."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
from openrouter import OpenRouter
from openrouter.errors import OpenRouterError
from openrouter.utils.retries import BackoffStrategy, RetryConfig
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from experiment.adapters import backends
from experiment.adapters import ollama as ollama_adapter
from experiment.domain.backend import BackendError, BackendProfile
from experiment.domain.prompts import ChatTurn

_RETRYABLE_STATUSES = ollama_adapter.RETRYABLE_STATUSES
_TOKEN_LIMIT_MARKERS = (
    "token limit",
    "context length",
    "context_length",
    "max_tokens",
    "too many tokens",
    "token quota",
)


def is_openrouter_profile(profile: BackendProfile) -> bool:
    """Return True when ``profile`` targets ``openrouter.ai``."""
    host = (urlparse(str(profile.base_url)).hostname or "").lower()
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


def resolve_api_key(profile: BackendProfile, explicit_key: str | None = None) -> str:
    """Resolve the API key for ``profile`` from an explicit override or configured env var."""
    if explicit_key:
        return explicit_key
    backends.require_api_key(profile)
    if profile.api_key_env:
        return os.environ[profile.api_key_env]
    return ""


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "[REDACTED]") if secret else text


def _error_status(exc: OpenRouterError) -> int:
    raw_resp = getattr(exc, "raw_response", None)
    status = getattr(raw_resp, "status_code", None) or getattr(exc, "status_code", None)
    return int(status) if isinstance(status, int) else 500


def _error_body(exc: OpenRouterError, secret: str) -> str:
    body = getattr(exc, "body", None) or getattr(exc, "message", None) or str(exc)
    return _redact(str(body), secret)[:300]


def build_client(
    profile: BackendProfile,
    *,
    api_key: str | None = None,
    client_factory: Callable[..., Any] = OpenRouter,
) -> Any:
    """Construct an official ``openrouter.OpenRouter`` SDK client for ``profile``."""
    key = resolve_api_key(profile, api_key)
    no_sdk_retry = RetryConfig(
        strategy="none",
        backoff=BackoffStrategy(100, 1000, 1.5, 1000),
        retry_connection_errors=False,
    )
    return client_factory(
        api_key=key or None,
        server_url=str(profile.base_url).rstrip("/"),
        timeout_ms=int(profile.read_timeout_s * 1000),
        retry_config=no_sdk_retry,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(mode="json", exclude_none=True)
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _normalize_usage(raw_usage: Any) -> dict[str, int] | None:
    usage_dict = _as_dict(raw_usage)
    if not usage_dict:
        return None
    out: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = usage_dict.get(key)
        if isinstance(val, int | float) and not isinstance(val, bool):
            out[key] = int(val)
    return out or None


def _normalize_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_calls, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, call in enumerate(raw_calls, start=1):
        call_dict = _as_dict(call)
        func = _as_dict(call_dict.get("function"))
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


def normalize_openrouter_chat_result(result: Any) -> dict[str, Any]:
    """Translate an OpenRouter ``ChatResult`` into the canonical OpenAI-style dict."""
    raw = _as_dict(result)
    raw_choices = raw.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise BackendError("invalid-response", "OpenRouter chat response contained no choices")
    first = _as_dict(raw_choices[0])
    raw_msg = _as_dict(first.get("message"))
    message: dict[str, Any] = {
        "role": str(raw_msg.get("role") or "assistant"),
        "content": raw_msg.get("content"),
    }
    tool_calls = _normalize_tool_calls(raw_msg.get("tool_calls"))
    if tool_calls:
        message["tool_calls"] = tool_calls
    payload: dict[str, Any] = {
        "choices": [{"message": message, "finish_reason": first.get("finish_reason") or "stop"}]
    }
    usage = _normalize_usage(raw.get("usage"))
    if usage is not None:
        payload["usage"] = usage
    return payload


def _translate_transport_error(
    exc: Exception, base_url: str, timeout_s: float, redacted: str
) -> BackendError:
    if isinstance(exc, httpx.TimeoutException):
        return BackendError("timeout", f"no response within {timeout_s}s from {base_url}")
    if isinstance(exc, httpx.ConnectError | ConnectionError | OSError):
        return BackendError("connection", f"cannot reach {base_url}: {redacted}")
    return BackendError("transport", f"{exc.__class__.__name__}: {redacted}")


def _is_retryable_openrouter_error(exc: BaseException) -> bool:
    return isinstance(exc, OpenRouterError) and _error_status(exc) in _RETRYABLE_STATUSES


def call_with_retry(
    operation: Callable[[], Any],
    profile: BackendProfile,
    *,
    secret: str,
    sleep: Callable[[float], None],
) -> Any:
    """Invoke an OpenRouter SDK call with ``tenacity`` 429/5xx retries and redacted errors."""
    retrying = Retrying(
        stop=stop_after_attempt(profile.retries + 1),
        wait=wait_exponential(multiplier=ollama_adapter.DEFAULT_RETRY_BACKOFF_S, exp_base=2),
        retry=retry_if_exception(_is_retryable_openrouter_error),
        reraise=True,
        sleep=sleep,
    )
    try:
        return retrying(operation)
    except (httpx.HTTPError, ConnectionError, OSError) as exc:
        redacted = _redact(str(exc), secret)
        raise _translate_transport_error(
            exc, str(profile.base_url), profile.read_timeout_s, redacted
        ) from exc


def _translate_chat_error(
    exc: OpenRouterError, profile: BackendProfile, secret: str
) -> BackendError:
    status = _error_status(exc)
    detail = _error_body(exc, secret)
    if status == 429:
        raw_resp = getattr(exc, "raw_response", None)
        headers = getattr(raw_resp, "headers", None) or {}
        retry_after = headers.get("Retry-After", "unspecified")
        return BackendError(
            "rate-limit",
            f"HTTP 429 after {profile.retries} retries (Retry-After: {retry_after}): {detail}",
        )
    return BackendError(f"http-{status}", detail)


class OpenRouterChatGateway:
    """``ChatGateway`` backed by the official ``openrouter.OpenRouter`` SDK."""

    def __init__(
        self,
        profile: BackendProfile,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profile = profile
        self._secret = "" if client is not None else resolve_api_key(profile)
        self._owns_client = client is None
        self._client = client if client is not None else build_client(profile, api_key=self._secret)
        self._sleep = sleep

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
        kwargs: dict[str, Any] = {
            "model": self._profile.model,
            "messages": messages,
            "temperature": self._profile.temperature,
            "max_tokens": self._profile.max_tokens,
            "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            result = call_with_retry(
                lambda: self._client.chat.send(**kwargs),
                self._profile,
                secret=self._secret,
                sleep=self._sleep,
            )
        except OpenRouterError as exc:
            raise _translate_chat_error(exc, self._profile, self._secret) from exc
        return normalize_openrouter_chat_result(result)

    def parse_turn(self, reply: dict[str, Any]) -> ChatTurn:
        return backends.parse_chat_turn(reply)

    def close(self) -> None:
        if self._owns_client and hasattr(self._client, "__exit__"):
            self._client.__exit__(None, None, None)


def _is_token_limit(status: int, detail: str) -> bool:
    lower = detail.lower()
    return status == 413 or any(marker in lower for marker in _TOKEN_LIMIT_MARKERS)


def _extract_model_ids(resp: Any) -> set[str]:
    raw = _as_dict(resp)
    nested = _as_dict(raw.get("result")) if "result" in raw else raw
    data = nested.get("data")
    if not isinstance(data, list):
        return set()
    ids: set[str] = set()
    for item in data:
        model_id = _as_dict(item).get("id")
        if isinstance(model_id, str) and model_id:
            ids.add(model_id)
    return ids


def classify_probe_error(
    exc: OpenRouterError, profile: BackendProfile, secret: str, *, for_completion: bool
) -> tuple[str, str, str]:
    """Map an ``OpenRouterError`` to ``(kind, detail, hint)`` for ``BackendProbeError``."""
    status = _error_status(exc)
    detail = _error_body(exc, secret)
    if status in (401, 403):
        hint = "check OPENROUTER_API_KEY (4xx is never retried)"
        return ("auth-error", f"HTTP {status} from OpenRouter: {detail}", hint)
    if for_completion and _is_token_limit(status, detail):
        hint = "reduce max_tokens or check model context window / provider quota"
        return ("token-limit", f"HTTP {status} token/context limit: {detail}", hint)
    if status == 429:
        msg = f"HTTP 429 rate/token limit after {profile.retries} retries: {detail}"
        return ("token-limit", msg, "wait for OpenRouter quota reset or lower concurrency")
    if 400 <= status < 500:
        kind = "completion-rejected" if for_completion else "client-error"
        return (kind, f"HTTP {status}: {detail}", "verify OpenRouter model slug and options")
    kind = "completion-rejected" if for_completion else "tunnel-dead"
    return (kind, f"HTTP {status} after retries: {detail}", "check OpenRouter service status")


def list_models_sdk(
    client: Any,
    profile: BackendProfile,
    *,
    secret: str,
    sleep: Callable[[float], None],
) -> set[str]:
    """List model IDs via ``OpenRouter.models.list()`` with 429/5xx-only retries."""
    resp = call_with_retry(
        lambda: client.models.list(),
        profile,
        secret=secret,
        sleep=sleep,
    )
    return _extract_model_ids(resp)
