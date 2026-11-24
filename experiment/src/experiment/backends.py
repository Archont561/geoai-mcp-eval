"""Chat-completion backends: TOML profiles validated with pydantic.

A profile is one OpenAI-compatible endpoint (local Ollama, remote Ollama over
an SSH tunnel, a hosted open model — all speak the same /v1/chat/completions).
Secrets never appear in the TOML: a profile names the environment variable that
holds the API key, and the key is read only when a session is built. Invalid
configuration fails fast with a BackendError before any network call or cell
run; the CLI maps that to exit code 2.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import requests
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from experiment.adapters import ollama as ollama_adapter
from experiment.adapters.paths import backends_path

DEFAULT_BACKENDS_PATH = backends_path()
DEFAULT_BASE_URL = ollama_adapter.DEFAULT_BASE_URL
DEFAULT_MODEL = "qwen2.5-coder:0.5b"
LOCAL_BACKEND = "local"


class BackendError(Exception):
    """Backend problem with a stable class token.

    str(BackendError) is ``"<error_class>: <detail>"`` — the harness records it
    verbatim as the cell error; the CLI turns config errors into exit code 2.
    """

    def __init__(self, error_class: str, detail: str) -> None:
        self.error_class = error_class
        self.detail = detail
        super().__init__(f"{error_class}: {detail}")


class BackendProfile(BaseModel):
    """One validated backend table from backends.toml."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_url: AnyHttpUrl
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    max_tokens: int = Field(default=2048, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    connect_timeout_s: float = Field(default=5.0, gt=0)
    read_timeout_s: float = Field(default=300.0, gt=0)
    retries: int = Field(default=3, ge=0)

    @property
    def chat_url(self) -> str:
        base = str(self.base_url).rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/chat/completions"

    @property
    def models_url(self) -> str:
        base = str(self.base_url).rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/models"

    @property
    def api_root(self) -> str:
        base = str(self.base_url).rstrip("/")
        return base[:-3] if base.endswith("/v1") else base

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout_s, self.read_timeout_s)


class BackendsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backends: dict[str, BackendProfile]


def load_profiles(path: Path | None = None) -> dict[str, BackendProfile]:
    path = path or DEFAULT_BACKENDS_PATH
    if not path.is_file():
        raise BackendError("config", f"backends file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise BackendError("config", f"{path}: {exc}") from exc
    try:
        return BackendsFile.model_validate(raw).backends
    except ValidationError as exc:
        raise BackendError("config", f"{path}: {exc}") from exc


def _normalize_host(host: str) -> str:
    return host.strip().rstrip("/")


def resolve_profile(
    backend: str | None,
    *,
    host: str | None = None,
    model: str | None = None,
    path: Path | None = None,
) -> BackendProfile:
    """Precedence: flag > $OLLAMA_HOST (local only) > file profile > built-in default."""
    path = path or DEFAULT_BACKENDS_PATH
    name = backend or LOCAL_BACKEND
    profiles = load_profiles(path) if path.is_file() else {}
    chosen = profiles.get(name)
    if chosen is None and name != LOCAL_BACKEND:
        if path.is_file():
            known = ", ".join(sorted(profiles)) or "none defined"
            raise BackendError("config", f"unknown backend {name!r}; known: {known}")
        msg = f"backends file not found: {path} (needed for --backend {name!r})"
        raise BackendError("config", msg)
    if chosen is None:
        chosen = BackendProfile(base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL)
    env_host = os.environ.get("OLLAMA_HOST") if name == LOCAL_BACKEND else None
    url = host or env_host or str(chosen.base_url)
    chosen_model = model or chosen.model
    data = chosen.model_dump(mode="json")
    data["base_url"] = _normalize_host(url)
    data["model"] = chosen_model
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
    return BackendProfile(base_url=_normalize_host(host), model=model)


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
    """Query Ollama ``/api/tags`` for the pinned model digest; return None if unavailable."""
    return ollama_adapter.resolve_model_digest(
        session,
        profile.api_root,
        profile.model,
        connect_timeout_s=profile.connect_timeout_s,
    )
