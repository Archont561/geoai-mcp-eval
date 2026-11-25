"""Backend profile I/O (TOML loading, env auth, HTTP retry sessions & chat POSTs)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from pydantic import ValidationError

from experiment.adapters import config as config_adapter
from experiment.adapters import ollama as ollama_adapter
from experiment.adapters.paths import config_path
from experiment.domain.backend import (
    DEFAULT_MODEL,
    LOCAL_BACKEND,
    BackendError,
    BackendProfile,
    BackendsFile,
    normalize_host,
)
from experiment.domain.prompts import ChatTurn, ToolCall

DEFAULT_CONFIG_PATH = config_path()
DEFAULT_BASE_URL = ollama_adapter.DEFAULT_BASE_URL

__all__ = [
    "BackendError",
    "BackendProfile",
    "BackendsFile",
    "DEFAULT_BASE_URL",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_MODEL",
    "LOCAL_BACKEND",
    "build_session",
    "chat_completions",
    "fallback_profile",
    "load_profiles",
    "parse_chat_turn",
    "require_api_key",
    "resolve_model_digest",
    "resolve_profile",
]


def load_profiles(path: Path | None = None) -> dict[str, BackendProfile]:
    """Load ``[backends.*]`` profiles from ``experiment.toml`` (or an explicit TOML file)."""
    target = path or config_path()
    if not target.is_file():
        raise BackendError("config", f"config file not found: {target}")
    return config_adapter.load_config(target, env={}).backends


def _select_profile(name: str, profiles: dict[str, BackendProfile], path: Path) -> BackendProfile:
    chosen = profiles.get(name)
    if chosen is not None:
        return chosen
    if name == LOCAL_BACKEND:
        return BackendProfile(base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL)
    if path.is_file():
        known = ", ".join(sorted(profiles)) or "none defined"
        raise BackendError("config", f"unknown backend {name!r}; known: {known}")
    msg = f"config file not found: {path} (needed for --backend {name!r})"
    raise BackendError("config", msg)


def resolve_profile(
    backend: str | None,
    *,
    host: str | None = None,
    model: str | None = None,
    path: Path | None = None,
) -> BackendProfile:
    """Precedence: flag > $OLLAMA_HOST (local only) > file profile > built-in default."""
    target = path or config_path()
    name = backend or LOCAL_BACKEND
    profiles = load_profiles(target) if target.is_file() else {}
    chosen = _select_profile(name, profiles, target)
    env_host = os.environ.get("OLLAMA_HOST") if name == LOCAL_BACKEND else None
    data = chosen.model_dump(mode="json")
    data["base_url"] = normalize_host(host or env_host or str(chosen.base_url))
    data["model"] = model or chosen.model
    try:
        return BackendProfile.model_validate(data)
    except ValidationError as exc:
        raise BackendError("config", f"invalid backend resolution for {name!r}: {exc}") from exc


def require_api_key(profile: BackendProfile) -> None:
    """Fail fast if PROFILE names an api_key_env whose value is missing."""
    if profile.api_key_env and not os.environ.get(profile.api_key_env):
        msg = f"environment variable {profile.api_key_env} is unset (backend needs it)"
        raise BackendError("config", msg)


def fallback_profile(host: str, model: str) -> BackendProfile:
    """Profile for ad-hoc runs that pass host/model directly (tests, no TOML)."""
    return BackendProfile(base_url=normalize_host(host), model=model)


def build_session(profile: BackendProfile) -> requests.Session:
    """Session carrying auth (if any) and the retry policy for PROFILE."""
    require_api_key(profile)
    headers = (
        {"Authorization": f"Bearer {os.environ[profile.api_key_env]}"}
        if profile.api_key_env
        else None
    )
    return ollama_adapter.build_retry_session(profile.retries, headers=headers)


def resolve_model_digest(session: requests.Session, profile: BackendProfile) -> str | None:
    """Resolve the pinned model digest via ``ollama.Client`` (or injected session)."""
    if ollama_adapter.is_ollama_profile(profile) and type(session) is requests.Session:
        return ollama_adapter.resolve_model_digest_sdk(profile.api_root, profile.model)
    return ollama_adapter.resolve_model_digest(
        session,
        profile.api_root,
        profile.model,
        connect_timeout_s=profile.connect_timeout_s,
    )


def _post_chat(
    session: requests.Session,
    profile: BackendProfile,
    body: dict[str, Any],
) -> requests.Response:
    try:
        return session.post(profile.chat_url, json=body, timeout=profile.timeout)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
        raise BackendError("connection", f"cannot reach {profile.base_url}: {exc}") from exc
    except requests.exceptions.ReadTimeout as exc:
        msg = f"no response within {profile.read_timeout_s}s from {profile.base_url}"
        raise BackendError("timeout", msg) from exc
    except requests.exceptions.RequestException as exc:
        raise BackendError("transport", f"{exc.__class__.__name__}: {exc}") from exc


def _parse_chat_response(resp: requests.Response, profile: BackendProfile) -> dict[str, Any]:
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unspecified")
        detail = f"HTTP 429 after {profile.retries} retries (Retry-After: {retry_after})"
        raise BackendError("rate-limit", detail)
    if resp.status_code >= 400:
        raise BackendError(f"http-{resp.status_code}", resp.text[:300])
    try:
        return resp.json()
    except ValueError as exc:
        raise BackendError("invalid-response", f"response is not JSON: {resp.text[:300]}") from exc


def chat_completions(
    session: requests.Session,
    profile: BackendProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """POST one OpenAI-compatible ``/v1/chat/completions`` request and return parsed JSON."""
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


def _parse_tool_call(raw_call: dict[str, Any]) -> ToolCall:
    func = raw_call.get("function") or {}
    name = str(func.get("name") or "")
    raw_args = str(func.get("arguments") or "{}")
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        parsed = {}
    arguments = parsed if isinstance(parsed, dict) else {}
    call_id = str(raw_call.get("id") or name)
    return ToolCall(call_id=call_id, name=name, arguments=arguments, raw_arguments=raw_args)


def parse_chat_turn(reply: dict[str, Any]) -> ChatTurn:
    """Translate one OpenAI ``/v1/chat/completions`` payload into a domain ``ChatTurn``."""
    message = dict(reply["choices"][0]["message"])
    raw_calls = message.get("tool_calls") or []
    calls = tuple(_parse_tool_call(call) for call in raw_calls if isinstance(call, dict))
    content = message.get("content")
    return ChatTurn(
        content=str(content) if content is not None else None,
        tool_calls=calls,
        raw_message=message,
    )
