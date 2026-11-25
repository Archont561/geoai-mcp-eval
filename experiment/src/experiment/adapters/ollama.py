"""Ollama Python SDK (``ollama.Client``) transport, digest lookup, and daemon lifecycle."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

import httpx
import ollama
import requests
from pydantic import BaseModel, ConfigDict, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from experiment.adapters import run_store
from experiment.domain.backend import BackendProfile

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_BACKOFF_S = 1.0
DEFAULT_READY_ATTEMPTS = 60
DEFAULT_READY_SLEEP_S = 2.0
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class HttpTransportError(RuntimeError):
    """Network/transport failure talking to an LLM HTTP endpoint."""


class RetryPolicy(BaseModel):
    """Retry parameters for transient 429/5xx HTTP responses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout: tuple[float, float]
    retries: int = Field(default=3, ge=0)
    backoff_s: float = Field(default=DEFAULT_RETRY_BACKOFF_S, ge=0.0)


# Non-serializable live OS process + open file handle; intentionally a dataclass, not a BaseModel.
@dataclass
class OllamaProcess:
    """Managed ``ollama serve`` child process and its open log stream."""

    proc: subprocess.Popen[bytes]
    log_handle: BinaryIO

    def stop(self) -> None:
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        finally:
            self.log_handle.close()


def is_ollama_profile(profile: BackendProfile) -> bool:
    """Return True when ``profile`` targets a local or forwarded Ollama daemon."""
    if profile.api_key_env:
        return False
    parsed = urlparse(str(profile.base_url))
    return (parsed.hostname or "").lower() in _LOCAL_HOSTS or parsed.port == 11434


def build_client(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout: float | httpx.Timeout | None = None,
    headers: Mapping[str, str] | None = None,
) -> ollama.Client:
    """Construct an official ``ollama.Client`` bound to ``base_url``."""
    kwargs: dict[str, Any] = {"host": base_url.rstrip("/")}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if headers:
        kwargs["headers"] = dict(headers)
    return ollama.Client(**kwargs)


def build_retry_session(
    retries: int,
    *,
    headers: Mapping[str, str] | None = None,
    allowed_methods: frozenset[str] = frozenset({"POST"}),
) -> requests.Session:
    """Session configured with optional headers and urllib3 retry policy."""
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    if headers:
        session.headers.update(headers)
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=0.8,
        status_forcelist=tuple(sorted(RETRYABLE_STATUSES)),
        respect_retry_after_header=True,
        allowed_methods=set(allowed_methods),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def request_with_retry(
    method: Callable[..., Any],
    url: str,
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """Issue an HTTP call; retry ONLY on 429/5xx according to ``policy``."""
    attempts = policy.retries + 1
    kwargs: dict[str, Any] = {"timeout": policy.timeout}
    if json_body is not None:
        kwargs["json"] = json_body
    last_resp: Any = None
    for attempt in range(attempts):
        try:
            resp = method(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise HttpTransportError(f"HTTP transport error reaching {url}: {exc}") from exc
        if resp.status_code not in RETRYABLE_STATUSES:
            return resp
        last_resp = resp
        if attempt + 1 < attempts:
            sleep(policy.backoff_s * (2**attempt))
    return last_resp


def as_mapping(value: Any) -> dict[str, Any]:
    """Convert an SDK response/model object or mapping into a plain dict."""
    if isinstance(value, Mapping):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _entry_digest(entry: object, candidates: set[str]) -> str | None:
    raw = as_mapping(entry)
    if not ({raw.get("name"), raw.get("model")} & candidates):
        return None
    digest = raw.get("digest")
    return digest.strip() if isinstance(digest, str) and digest.strip() else None


def extract_digest_from_tags(payload: object, model: str) -> str | None:
    """Extract the pinned digest for ``model`` from an Ollama ``list()`` / ``/api/tags`` payload."""
    raw = as_mapping(payload)
    models = raw.get("models")
    if not isinstance(models, list):
        return None
    candidates = {model, f"{model}:latest"} if ":" not in model else {model}
    for entry in models:
        digest = _entry_digest(entry, candidates)
        if digest:
            return digest
    return None


def list_model_entries(
    base_url: str = DEFAULT_BASE_URL,
    *,
    client: Any | None = None,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """List installed models via ``ollama.Client.list()`` as normalized dictionaries."""
    active = client if client is not None else build_client(base_url, timeout=timeout)
    payload = as_mapping(active.list())
    models = payload.get("models")
    return [as_mapping(entry) for entry in models] if isinstance(models, list) else []


def resolve_model_digest_sdk(
    base_url: str,
    model: str,
    *,
    client: Any | None = None,
    timeout: float = 10.0,
) -> str | None:
    """Resolve ``model`` digest through ``ollama.Client.list()``; return None on errors."""
    try:
        entries = list_model_entries(base_url, client=client, timeout=timeout)
    except (ollama.RequestError, ollama.ResponseError, httpx.HTTPError, OSError):
        return None
    return extract_digest_from_tags({"models": entries}, model)


def resolve_model_digest(
    session: Any,
    api_root: str,
    model: str,
    *,
    connect_timeout_s: float = 5.0,
) -> str | None:
    """Query Ollama ``/api/tags`` via a requests session, or ``ollama.Client`` if None."""
    if session is None or isinstance(session, ollama.Client):
        return resolve_model_digest_sdk(api_root, model, client=session, timeout=10.0)
    try:
        resp = session.get(f"{api_root.rstrip('/')}/api/tags", timeout=(connect_timeout_s, 10))
    except requests.exceptions.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    return extract_digest_from_tags(payload, model)


def serve_running(base_url: str = DEFAULT_BASE_URL, *, client: Any | None = None) -> bool:
    """Return True when ``ollama.Client.list()`` succeeds against ``base_url``."""
    active = client if client is not None else build_client(base_url, timeout=2.0)
    try:
        active.list()
    except (ollama.RequestError, ollama.ResponseError, httpx.HTTPError, OSError):
        return False
    return True


def wait_ready(
    base_url: str = DEFAULT_BASE_URL,
    *,
    attempts: int = DEFAULT_READY_ATTEMPTS,
    sleep_s: float = DEFAULT_READY_SLEEP_S,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll Ollama via ``ollama.Client`` until ready or ``attempts`` are exhausted."""
    for _ in range(attempts):
        if serve_running(base_url):
            return True
        sleep(sleep_s)
    return False


def start_ollama(
    ollama_bin: str,
    serve_log: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> OllamaProcess | None:
    """Spawn ``ollama serve`` unless a daemon is already responding on ``base_url``."""
    if serve_running(base_url):
        return None
    run_store.ensure_dir(serve_log.parent)
    handle = serve_log.open("wb")
    proc = subprocess.Popen(
        [ollama_bin, "serve"],
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return OllamaProcess(proc=proc, log_handle=handle)


def stop_ollama(owner: OllamaProcess | None) -> None:
    """Stop a daemon started by :func:`start_ollama` (no-op if None)."""
    if owner is not None:
        owner.stop()


def pull_model(
    ollama_bin: str,
    model: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: int = 1800,
) -> int:
    """Pull ``model`` via ``ollama.Client.pull()`` and return 0 on success or 1 on error."""
    _ = ollama_bin  # Retained in signature for callers that resolve the daemon binary first.
    active = build_client(base_url, timeout=float(timeout_s))
    try:
        active.pull(model, stream=False)
    except (ollama.RequestError, ollama.ResponseError, httpx.HTTPError, OSError):
        return 1
    return 0


def smoke_generate(
    model: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Issue a minimal non-streaming ``generate`` probe via ``ollama.Client``."""
    active = build_client(base_url, timeout=timeout_s)
    response = active.generate(
        model=model,
        prompt="Reply with: OK",
        stream=False,
        options={"temperature": 0},
    )
    return as_mapping(response)


def list_model_digest(
    ollama_bin: str,
    model: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    client: Any | None = None,
) -> str:
    """Resolve ``model`` digest via ``ollama.Client.list()``, or ``unavailable``."""
    _ = ollama_bin
    digest = resolve_model_digest_sdk(base_url, model, client=client)
    return digest or "unavailable"
