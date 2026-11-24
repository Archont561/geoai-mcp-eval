"""Ollama / OpenAI-compatible HTTP transport, digest lookup, and daemon lifecycle."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from experiment.adapters import run_store, subprocess_runner

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_BACKOFF_S = 1.0
DEFAULT_READY_ATTEMPTS = 60
DEFAULT_READY_SLEEP_S = 2.0


class HttpTransportError(RuntimeError):
    """Network/transport failure talking to an LLM HTTP endpoint."""


@dataclass(frozen=True)
class RetryPolicy:
    """Retry parameters for transient 429/5xx HTTP responses."""

    timeout: tuple[float, float]
    retries: int = 3
    backoff_s: float = DEFAULT_RETRY_BACKOFF_S


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


def create_session() -> requests.Session:
    """Build a plain requests Session for callers outside the adapter layer."""
    return requests.Session()


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


def extract_digest_from_tags(payload: object, model: str) -> str | None:
    """Extract the pinned digest for ``model`` from an Ollama ``/api/tags`` JSON payload."""
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    if not isinstance(models, list):
        return None
    candidates = {model, f"{model}:latest"} if ":" not in model else {model}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        names = {entry.get("name"), entry.get("model")}
        if names & candidates:
            digest = entry.get("digest")
            if isinstance(digest, str) and digest.strip():
                return digest.strip()
    return None


def resolve_model_digest(
    session: Any,
    api_root: str,
    model: str,
    *,
    connect_timeout_s: float = 5.0,
) -> str | None:
    """Query Ollama ``/api/tags`` for the pinned model digest; return None if unavailable."""
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


def serve_running(base_url: str = DEFAULT_BASE_URL) -> bool:
    """Return True if an Ollama server responds HTTP 200 on ``/api/version``."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/version", timeout=2)
    except requests.exceptions.RequestException:
        return False
    return resp.status_code == 200


def wait_ready(
    base_url: str = DEFAULT_BASE_URL,
    *,
    attempts: int = DEFAULT_READY_ATTEMPTS,
    sleep_s: float = DEFAULT_READY_SLEEP_S,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll ``/api/version`` until Ollama is ready or ``attempts`` are exhausted."""
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


def pull_model(ollama_bin: str, model: str, *, timeout_s: int = 1800) -> int:
    """Pull ``model`` via the Ollama CLI and return its exit code."""
    return subprocess_runner.run_passthrough([ollama_bin, "pull", model], timeout=timeout_s)


def smoke_generate(
    model: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Issue a minimal non-streaming ``/api/generate`` probe against local Ollama."""
    body = {
        "model": model,
        "prompt": "Reply with: OK",
        "stream": False,
        "options": {"temperature": 0},
    }
    resp = requests.post(f"{base_url.rstrip('/')}/api/generate", json=body, timeout=timeout_s)
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def list_model_digest(
    ollama_bin: str,
    model: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    """Resolve ``model`` digest via ``/api/tags``, falling back to ``ollama list`` CLI."""
    with create_session() as session:
        digest = resolve_model_digest(session, base_url, model)
    if digest:
        return digest
    result = subprocess_runner.run_command([ollama_bin, "list"], timeout=60)
    prefix = model.split(":", 1)[0]
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and (parts[0] == model or parts[0].startswith(prefix)):
            return parts[1] if len(parts) > 1 else "unavailable"
    return "unavailable"
