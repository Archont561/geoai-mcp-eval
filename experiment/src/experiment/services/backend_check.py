"""Remote-Ollama preflight verification service (GEO-010).

Verifies SSH host reachability and ControlMaster tunnel health, polls
``/v1/models`` and ``/api/tags`` until the expected model digest appears, and
issues one tiny completion before returning ``READY`` with the pinned digest.

Retry policy: never silently retries auth/4xx responses; retries only transient
429/5xx responses up to the backend profile's ``retries`` limit.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiment.adapters import backends, subprocess_runner
from experiment.adapters import ollama as ollama_adapter
from experiment.adapters.github_workflow import GitHubWorkflowAdapter

EXIT_READY = 0
EXIT_SSH_UNREACHABLE = 10
EXIT_TUNNEL_DEAD = 11
EXIT_MODEL_ABSENT = 12
EXIT_AUTH_CLIENT = 13
EXIT_TOKEN_LIMIT = 14
EXIT_COMPLETION_REJECTED = 15

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


@dataclass(frozen=True)
class _CheckRuntime:
    """Resolved runtime bundle threaded through HTTP probe stages."""

    cfg: BackendCheckConfig
    profile: backends.BackendProfile
    session: Any
    sleep: Callable[[float], None]


def default_run_cmd(cmd: list[str], *, timeout: float) -> subprocess_runner.CommandResult:
    """Default subprocess runner for SSH/ControlMaster probes."""
    return subprocess_runner.run_command(cmd, timeout=timeout)


def _probe_ssh_host(ssh_host: str, run_cmd: Callable[..., Any]) -> None:
    probe_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ssh_host, "true"]
    try:
        ssh_res = run_cmd(probe_cmd, timeout=10.0)
    except (OSError, subprocess_runner.CommandTimeoutError, TimeoutError) as exc:
        raise BackendCheckError(
            "ssh-unreachable",
            EXIT_SSH_UNREACHABLE,
            f"cannot reach SSH host {ssh_host}: {exc}",
            "verify network/VPN connectivity, SSH config, and key authentication",
        ) from exc
    if ssh_res.returncode != 0:
        stderr = (getattr(ssh_res, "stderr", "") or "").strip() or f"exit {ssh_res.returncode}"
        raise BackendCheckError(
            "ssh-unreachable",
            EXIT_SSH_UNREACHABLE,
            f"SSH host {ssh_host} unreachable ({stderr})",
            "check hostname, SSH keys, and firewall rules",
        )


def _probe_control_tunnel(
    ssh_host: str, control_path: Path | None, run_cmd: Callable[..., Any]
) -> None:
    ctrl_cmd = ["ssh", "-O", "check"]
    if control_path is not None:
        ctrl_cmd.extend(["-S", str(control_path)])
    ctrl_cmd.append(ssh_host)
    try:
        ctrl_res = run_cmd(ctrl_cmd, timeout=10.0)
    except (OSError, subprocess_runner.CommandTimeoutError, TimeoutError) as exc:
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"SSH ControlMaster check failed for {ssh_host}: {exc}",
            "restart the ControlMaster tunnel before running the experiment",
        ) from exc
    if ctrl_res.returncode != 0:
        stderr = (getattr(ctrl_res, "stderr", "") or "").strip() or f"exit {ctrl_res.returncode}"
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"SSH ControlMaster tunnel is not running ({stderr})",
            f"re-establish the ControlMaster tunnel to {ssh_host}",
        )


def _verify_ssh_and_tunnel(cfg: BackendCheckConfig, run_cmd: Callable[..., Any]) -> None:
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
    _probe_ssh_host(cfg.ssh_host, run_cmd)
    _probe_control_tunnel(cfg.ssh_host, cfg.control_path, run_cmd)


def _is_token_limit(status_code: int, text: str) -> bool:
    lower = text.lower()
    if any(marker in lower for marker in _TOKEN_LIMIT_MARKERS):
        return True
    return status_code == 413


def _request_with_policy(
    method: Callable[..., Any],
    url: str,
    rt: _CheckRuntime,
    *,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """Issue one HTTP request; retry ONLY on 429/5xx per profile.retries."""
    policy = ollama_adapter.RetryPolicy(timeout=rt.profile.timeout, retries=rt.profile.retries)
    try:
        return ollama_adapter.request_with_retry(
            method, url, policy, sleep=rt.sleep, json_body=json_body
        )
    except ollama_adapter.HttpTransportError as exc:
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            str(exc),
            "verify port forwarding and that Ollama is listening on the remote host",
        ) from exc


def _entry_model_id(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("id")
    return str(model_id) if isinstance(model_id, str) else None


def _extract_model_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    data = payload.get("data")
    if not isinstance(data, list):
        return set()
    ids: set[str] = set()
    for entry in data:
        model_id = _entry_model_id(entry)
        if model_id is not None:
            ids.add(model_id)
    return ids


def _raise_for_models_http_status(resp: Any, url: str) -> None:
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


def _check_models_status(resp: Any, url: str) -> set[str]:
    _raise_for_models_http_status(resp, url)
    try:
        return _extract_model_ids(resp.json())
    except ValueError as exc:
        raise BackendCheckError(
            "tunnel-dead",
            EXIT_TUNNEL_DEAD,
            f"non-JSON response from {url}",
            "verify the forwarded port actually terminates at Ollama",
        ) from exc


def _check_digest_once(rt: _CheckRuntime) -> tuple[str | None, str]:
    resp = _request_with_policy(rt.session.get, rt.profile.models_url, rt)
    model_ids = _check_models_status(resp, rt.profile.models_url)
    candidates = {rt.profile.model, f"{rt.profile.model}:latest"}
    if not (model_ids & candidates):
        return None, f"model {rt.profile.model!r} not listed by {rt.profile.models_url}"
    digest = backends.resolve_model_digest(rt.session, rt.profile)
    expected = rt.cfg.expected_digest
    if digest and (expected is None or digest == expected):
        return digest, ""
    if expected:
        return None, f"model {rt.profile.model!r} digest {digest!r} != expected {expected!r}"
    return None, f"model {rt.profile.model!r} reported no digest from /api/tags"


def _poll_model_and_digest(rt: _CheckRuntime) -> str:
    deadline = time.monotonic() + max(0.0, rt.cfg.poll_timeout_s)
    while True:
        digest, reason = _check_digest_once(rt)
        if digest is not None:
            return digest
        if time.monotonic() >= deadline:
            raise BackendCheckError(
                "model-absent",
                EXIT_MODEL_ABSENT,
                reason,
                f"pull/pin `{rt.profile.model}` on the remote Ollama host and retry",
            )
        rt.sleep(rt.cfg.poll_interval_s)


def _validate_completion_response(resp: Any, profile: backends.BackendProfile) -> None:
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


def _parse_completion_payload(resp: Any, chat_url: str) -> None:
    try:
        payload = resp.json()
    except ValueError as exc:
        raise BackendCheckError(
            "completion-rejected",
            EXIT_COMPLETION_REJECTED,
            f"invalid JSON from {chat_url}",
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


def _run_tiny_completion(rt: _CheckRuntime) -> None:
    body = {
        "model": rt.profile.model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "temperature": 0.0,
        "max_tokens": rt.cfg.max_tokens,
    }
    resp = _request_with_policy(rt.session.post, rt.profile.chat_url, rt, json_body=body)
    _validate_completion_response(resp, rt.profile)
    _parse_completion_payload(resp, rt.profile.chat_url)


def emit_github_outputs(
    result: BackendCheckResult, gh: GitHubWorkflowAdapter | None = None
) -> None:
    """Publish backend-check result fields to ``$GITHUB_OUTPUT`` when running in CI."""
    adapter = gh or GitHubWorkflowAdapter()
    adapter.write_outputs(
        {
            "status": result.status,
            "backend": result.backend,
            "model": result.model,
            "digest": result.digest,
            "base_url": result.base_url,
        }
    )


def _resolve_check_profile(cfg: BackendCheckConfig) -> backends.BackendProfile:
    try:
        return backends.resolve_profile(cfg.backend, host=cfg.host, model=cfg.model)
    except backends.BackendError as exc:
        raise BackendCheckError(
            "client-error",
            EXIT_AUTH_CLIENT,
            str(exc),
            "check --backend / experiment/backends.toml",
        ) from exc


def run_backend_check(
    cfg: BackendCheckConfig,
    *,
    run_cmd: Callable[..., Any] = default_run_cmd,
    session: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackendCheckResult:
    """Run the full remote-Ollama preflight check and return READY + digest pin."""
    profile = _resolve_check_profile(cfg)
    _verify_ssh_and_tunnel(cfg, run_cmd)
    owns_session = session is None
    active_session = session if session is not None else ollama_adapter.create_session()
    rt = _CheckRuntime(cfg=cfg, profile=profile, session=active_session, sleep=sleep)
    try:
        digest = _poll_model_and_digest(rt)
        _run_tiny_completion(rt)
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
