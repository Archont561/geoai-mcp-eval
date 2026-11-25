"""Remote-Ollama preflight verification service (GEO-010).

Coordinates SSH tunnel verification, model/digest polling, and a minimal
completion check via typed :class:`TunnelProbe` and :class:`BackendProbe`
ports. Transport details (SSH CLI, HTTP status/retry semantics) live in
:mod:`experiment.adapters.ssh_tunnel` and :mod:`experiment.adapters.backend_probe`;
CLI exit-code mapping lives in :mod:`experiment.cli.env`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from experiment.adapters import backends
from experiment.adapters.backend_probe import BackendProbeError, create_backend_probe
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.adapters.ssh_tunnel import SshTunnelAdapter, TunnelProbeError
from experiment.domain.backend import BackendProfile


class BackendCheckError(RuntimeError):
    """Actionable, categorized preflight failure (CLI maps ``kind`` to an exit code)."""

    def __init__(self, kind: str, detail: str, hint: str) -> None:
        self.kind = kind
        self.detail = detail
        self.hint = hint
        super().__init__(f"[{kind}] {detail}. Next step: {hint}")


class BackendCheckConfig(BaseModel):
    """Parameters for a remote-Ollama preflight check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str = "remote-ollama"
    ssh_host: str | None = None
    control_path: Path | None = None
    expected_digest: str | None = None
    model: str | None = None
    host: str | None = None
    poll_timeout_s: float = Field(default=30.0, ge=0.0)
    poll_interval_s: float = Field(default=1.0, ge=0.0)
    max_tokens: int = Field(default=16, ge=1)


class BackendCheckResult(BaseModel):
    """Confirmed preflight result with pinned model digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    backend: str
    model: str
    digest: str
    base_url: str


class TunnelProbe(Protocol):
    """Port for verifying SSH reachability and an active ControlMaster tunnel."""

    def verify(self, ssh_host: str | None, control_path: Path | None) -> None:
        """Raise :class:`TunnelProbeError` when the SSH host or tunnel is unavailable."""


class BackendProbe(Protocol):
    """Port for probing an OpenAI-compatible / Ollama backend over HTTP."""

    def list_model_ids(self) -> set[str]:
        """Return advertised model identifiers from ``/v1/models``."""

    def resolve_model_digest(self) -> str | None:
        """Return the pinned digest for the configured model, or None if absent."""

    def verify_tiny_completion(self, *, max_tokens: int) -> None:
        """Execute one tiny completion and raise :class:`BackendProbeError` on failure."""

    def close(self) -> None:
        """Release any underlying transport resources."""


def _resolve_check_profile(cfg: BackendCheckConfig) -> BackendProfile:
    try:
        return backends.resolve_profile(cfg.backend, host=cfg.host, model=cfg.model)
    except backends.BackendError as exc:
        raise BackendCheckError(
            "client-error",
            str(exc),
            "check --backend / experiment/backends.toml",
        ) from exc


def _verify_tunnel(cfg: BackendCheckConfig, probe: TunnelProbe) -> None:
    try:
        probe.verify(cfg.ssh_host, cfg.control_path)
    except TunnelProbeError as exc:
        raise BackendCheckError(exc.kind, exc.detail, exc.hint) from exc


def _check_digest_once(
    cfg: BackendCheckConfig, profile: BackendProfile, probe: BackendProbe
) -> tuple[str | None, str]:
    model_ids = probe.list_model_ids()
    candidates = {profile.model, f"{profile.model}:latest"}
    if not (model_ids & candidates):
        return None, f"model {profile.model!r} not listed by {profile.models_url}"
    digest = probe.resolve_model_digest()
    expected = cfg.expected_digest
    if digest and (expected is None or digest == expected):
        return digest, ""
    if expected:
        return None, f"model {profile.model!r} digest {digest!r} != expected {expected!r}"
    return None, f"model {profile.model!r} reported no digest from /api/tags"


def _poll_model_and_digest(
    cfg: BackendCheckConfig,
    profile: BackendProfile,
    probe: BackendProbe,
    sleep: Callable[[float], None],
) -> str:
    deadline = time.monotonic() + max(0.0, cfg.poll_timeout_s)
    while True:
        digest, reason = _check_digest_once(cfg, profile, probe)
        if digest is not None:
            return digest
        if time.monotonic() >= deadline:
            raise BackendCheckError(
                "model-absent",
                reason,
                f"pull/pin `{profile.model}` on the remote Ollama host and retry",
            )
        sleep(cfg.poll_interval_s)


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


def run_backend_check(
    cfg: BackendCheckConfig,
    *,
    tunnel_probe: TunnelProbe | None = None,
    backend_probe: BackendProbe | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackendCheckResult:
    """Run the full backend preflight check and return READY + digest pin."""
    profile = _resolve_check_profile(cfg)
    if cfg.backend == "remote-ollama" or cfg.ssh_host is not None or tunnel_probe is not None:
        _verify_tunnel(cfg, tunnel_probe or SshTunnelAdapter())
    owns_probe = backend_probe is None
    active_probe: BackendProbe = (
        backend_probe if backend_probe is not None else create_backend_probe(profile, sleep=sleep)
    )
    try:
        digest = _poll_model_and_digest(cfg, profile, active_probe, sleep)
        active_probe.verify_tiny_completion(max_tokens=cfg.max_tokens)
    except BackendProbeError as exc:
        raise BackendCheckError(exc.kind, exc.detail, exc.hint) from exc
    finally:
        if owns_probe:
            active_probe.close()
    return BackendCheckResult(
        status="READY",
        backend=cfg.backend,
        model=profile.model,
        digest=digest,
        base_url=str(profile.base_url),
    )
