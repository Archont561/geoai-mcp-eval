"""Remote-Ollama preflight verification service (GEO-010).

Verifies SSH host reachability and ControlMaster tunnel health, polls
``/v1/models`` and ``/api/tags`` until the expected model digest appears, and
issues one tiny completion before returning ``READY`` with the pinned digest.

Retry policy: never silently retries auth/4xx responses; retries only transient
429/5xx responses up to the backend profile's ``retries`` limit.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from experiment import backends

EXIT_READY = 0
EXIT_SSH_UNREACHABLE = 10
EXIT_TUNNEL_DEAD = 11
EXIT_MODEL_ABSENT = 12
EXIT_AUTH_CLIENT = 13
EXIT_TOKEN_LIMIT = 14
EXIT_COMPLETION_REJECTED = 15

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_BACKOFF_S = 1.0
_TOKEN_LIMIT_MARKERS = (
    "token limit",
    "context length",
    "context_length",
    "max_tokens",
    "too many tokens",
    "token quota",
)


class BackendCheckError(RuntimeError):
    """Actionable, categorized preflight failure with a distinct exit code."""

    def __init__(self, kind: str, exit_code: int, detail: str, hint: str) -> None:
        self.kind = kind
        self.exit_code = exit_code
        self.detail = detail
        self.hint = hint
        super().__init__(f"[{kind}] {detail}. Next step: {hint}")


@dataclass(frozen=True)
class BackendCheckConfig:
    """Parameters for a remote-Ollama preflight check."""

    backend: str = "remote-ollama"
    ssh_host: str | None = None
    control_path: Path | None = None
    expected_digest: str | None = None
    model: str | None = None
    host: str | None = None
    poll_timeout_s: float = 30.0
    poll_interval_s: float = 1.0
    max_tokens: int = 16


@dataclass(frozen=True)
class BackendCheckResult:
    """Confirmed preflight result with pinned model digest."""

    status: str
    backend: str
    model: str
    digest: str
    base_url: str


def _default_run_cmd(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _verify_ssh_and_tunnel(
    cfg: BackendCheckConfig,
    run_cmd: Callable[..., Any],
) -> None:
    if not cfg.ssh_host:
        raise BackendCheckError(
            "ssh-unreachable",
            EXIT_SSH_UNREACHABLE,
            "no SSH host configured for remote-ollama preflight",
            "pass --ssh-host <user@host> (or set OLLAMA_SSH_HOST)",
        )
    if cfg.control_path is not None and not cfg.control_path.exists():
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"ControlMaster socket does not exist: {cfg.control_path}",
            f"open the SSH tunnel with `ssh -M -S {cfg.control_path} -fNT -L ... {cfg.ssh_host}`",
        )
    probe_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", cfg.ssh_host, "true"]
    try:
        ssh_res = run_cmd(probe_cmd, timeout=10.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendCheckError(
            "ssh-unreachable",
            EXIT_SSH_UNREACHABLE,
            f"cannot reach SSH host {cfg.ssh_host}: {exc}",
            "verify network/VPN connectivity, SSH config, and key authentication",
        ) from exc
    if ssh_res.returncode != 0:
        stderr = (getattr(ssh_res, "stderr", "") or "").strip() or f"exit {ssh_res.returncode}"
        raise BackendCheckError(
            "ssh-unreachable",
            EXIT_SSH_UNREACHABLE,
            f"SSH host {cfg.ssh_host} unreachable ({stderr})",
            "check hostname, SSH keys, and firewall rules",
        )
    ctrl_cmd = ["ssh", "-O", "check"]
    if cfg.control_path is not None:
        ctrl_cmd.extend(["-S", str(cfg.control_path)])
    ctrl_cmd.append(cfg.ssh_host)
    try:
        ctrl_res = run_cmd(ctrl_cmd, timeout=10.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"SSH ControlMaster check failed for {cfg.ssh_host}: {exc}",
            "restart the ControlMaster tunnel before running the experiment",
        ) from exc
    if ctrl_res.returncode != 0:
        stderr = (getattr(ctrl_res, "stderr", "") or "").strip() or f"exit {ctrl_res.returncode}"
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"SSH ControlMaster tunnel is not running ({stderr})",
            f"re-establish the ControlMaster tunnel to {cfg.ssh_host}",
        )


def _is_token_limit(status_code: int, text: str) -> bool:
    lower = text.lower()
    if any(marker in lower for marker in _TOKEN_LIMIT_MARKERS):
        return True
    return status_code == 413


def _request_with_policy(
    method: Callable[..., Any],
    url: str,
    profile: backends.BackendProfile,
    *,
    sleep: Callable[[float], None],
    **kwargs: Any,
) -> Any:
    """Issue one HTTP request; retry ONLY on 429/5xx per profile.retries."""
    attempts = profile.retries + 1
    last_resp: Any = None
    for attempt in range(attempts):
        try:
            resp = method(url, timeout=profile.timeout, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise BackendCheckError(
                "tunnel-dead",
                EXIT_TUNNEL_DEAD,
                f"HTTP transport error reaching {url}: {exc}",
                "verify port forwarding and that Ollama is listening on the remote host",
            ) from exc
        if resp.status_code not in _RETRYABLE_STATUSES:
            return resp
        last_resp = resp
        if attempt + 1 < attempts:
            sleep(_RETRY_BACKOFF_S * (2**attempt))
    return last_resp


def _extract_model_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    data = payload.get("data")
    if not isinstance(data, list):
        return set()
    return {
        str(entry["id"])
        for entry in data
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def _check_models_status(resp: Any, url: str) -> set[str]:
    if resp.status_code in (401, 403):
        raise BackendCheckError(
            "auth-error",
            EXIT_AUTH_CLIENT,
            f"HTTP {resp.status_code} from {url}: {resp.text[:200]}",
            "check API credentials or proxy auth configuration (4xx is never retried)",
        )
    if 400 <= resp.status_code < 500:
        raise BackendCheckError(
            "client-error",
            EXIT_AUTH_CLIENT,
            f"HTTP {resp.status_code} from {url}: {resp.text[:200]}",
            "verify backend base_url and OpenAI-compatible /v1/models path",
        )
    if resp.status_code >= 500:
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"HTTP {resp.status_code} from {url} after retries: {resp.text[:200]}",
            "inspect remote Ollama server logs",
        )
    try:
        return _extract_model_ids(resp.json())
    except ValueError as exc:
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"non-JSON response from {url}",
            "verify the forwarded port actually terminates at Ollama",
        ) from exc


def _poll_model_and_digest(
    session: requests.Session,
    profile: backends.BackendProfile,
    cfg: BackendCheckConfig,
    *,
    sleep: Callable[[float], None],
) -> str:
    deadline = time.monotonic() + max(0.0, cfg.poll_timeout_s)
    last_reason = f"model {profile.model!r} not listed by {profile.models_url}"
    while True:
        resp = _request_with_policy(session.get, profile.models_url, profile, sleep=sleep)
        model_ids = _check_models_status(resp, profile.models_url)
        candidates = {profile.model, f"{profile.model}:latest"}
        if model_ids & candidates:
            digest = backends.resolve_model_digest(session, profile)
            if digest and (cfg.expected_digest is None or digest == cfg.expected_digest):
                return digest
            if cfg.expected_digest:
                last_reason = (
                    f"model {profile.model!r} digest {digest!r} != expected {cfg.expected_digest!r}"
                )
            else:
                last_reason = f"model {profile.model!r} reported no digest from /api/tags"
        if time.monotonic() >= deadline:
            raise BackendCheckError(
                "model-absent",
                EXIT_MODEL_ABSENT,
                last_reason,
                f"pull/pin `{profile.model}` on the remote Ollama host and retry",
            )
        sleep(cfg.poll_interval_s)


def _run_tiny_completion(
    session: requests.Session,
    profile: backends.BackendProfile,
    cfg: BackendCheckConfig,
    *,
    sleep: Callable[[float], None],
) -> None:
    body = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "temperature": 0.0,
        "max_tokens": cfg.max_tokens,
    }
    resp = _request_with_policy(session.post, profile.chat_url, profile, sleep=sleep, json=body)
    if resp.status_code in (401, 403):
        raise BackendCheckError(
            "auth-error",
            EXIT_AUTH_CLIENT,
            f"HTTP {resp.status_code} on completion: {resp.text[:200]}",
            "verify credentials; auth errors are never retried",
        )
    if _is_token_limit(resp.status_code, resp.text):
        raise BackendCheckError(
            "token-limit",
            EXIT_TOKEN_LIMIT,
            f"HTTP {resp.status_code} token/context limit: {resp.text[:200]}",
            "reduce max_tokens or check model context window / provider token quota",
        )
    if resp.status_code == 429:
        raise BackendCheckError(
            "token-limit",
            EXIT_TOKEN_LIMIT,
            f"HTTP 429 rate/token limit after {profile.retries} retries: {resp.text[:200]}",
            "wait for quota reset or lower concurrency",
        )
    if resp.status_code >= 400:
        raise BackendCheckError(
            "completion-rejected",
            EXIT_COMPLETION_REJECTED,
            f"HTTP {resp.status_code} completion rejected: {resp.text[:200]}",
            "check model load state and remote Ollama logs",
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise BackendCheckError(
            "completion-rejected",
            EXIT_COMPLETION_REJECTED,
            f"invalid JSON from {profile.chat_url}",
            "inspect remote proxy/Ollama response",
        ) from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise BackendCheckError(
            "completion-rejected",
            EXIT_COMPLETION_REJECTED,
            "completion response contained no choices",
            "check remote Ollama model health",
        )


def run_backend_check(
    cfg: BackendCheckConfig,
    *,
    run_cmd: Callable[..., Any] = _default_run_cmd,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackendCheckResult:
    """Run the full remote-Ollama preflight check and return READY + digest pin."""
    try:
        profile = backends.resolve_profile(cfg.backend, host=cfg.host, model=cfg.model)
    except backends.BackendError as exc:
        raise BackendCheckError(
            "client-error",
            EXIT_AUTH_CLIENT,
            str(exc),
            "check --backend / experiment/backends.toml",
        ) from exc
    _verify_ssh_and_tunnel(cfg, run_cmd)
    owns_session = session is None
    active_session = session if session is not None else requests.Session()
    try:
        digest = _poll_model_and_digest(active_session, profile, cfg, sleep=sleep)
        _run_tiny_completion(active_session, profile, cfg, sleep=sleep)
    finally:
        if owns_session:
            active_session.close()
    return BackendCheckResult(
        status="READY",
        backend=cfg.backend,
        model=profile.model,
        digest=digest,
        base_url=str(profile.base_url),
    )
