"""Programmatic SSH port-forwarding and reachability adapter backed by ``sshtunnel``."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import paramiko
import sshtunnel

TunnelErrorKind = Literal["ssh-unreachable", "tunnel-dead"]
DEFAULT_SSH_PORT = 22
DEFAULT_REMOTE_OLLAMA_BIND: tuple[str, int] = ("127.0.0.1", 11434)


class TunnelProbeError(RuntimeError):
    """Structured SSH/tunnel failure carrying semantic kind and remediation hint."""

    def __init__(self, kind: TunnelErrorKind, detail: str, hint: str) -> None:
        self.kind = kind
        self.detail = detail
        self.hint = hint
        super().__init__(f"[{kind}] {detail}. Next step: {hint}")


@dataclass(frozen=True)
class SshTarget:
    """Parsed SSH connection target (optional user, hostname, and TCP port)."""

    username: str | None
    host: str
    port: int = DEFAULT_SSH_PORT


@dataclass(frozen=True)
class TunnelSpec:
    """Configuration for one managed ``sshtunnel.SSHTunnelForwarder`` instance."""

    ssh_host: str
    remote_bind_address: tuple[str, int] = DEFAULT_REMOTE_OLLAMA_BIND
    local_bind_address: tuple[str, int] = ("127.0.0.1", 0)
    ssh_pkey: Path | None = None
    ssh_password: str | None = None


def parse_ssh_target(raw: str) -> SshTarget:
    """Parse ``[user@]host[:port]`` into an :class:`SshTarget`."""
    text = raw.strip()
    if not text:
        raise TunnelProbeError(
            "ssh-unreachable",
            "no SSH host configured for remote-ollama preflight",
            "pass --ssh-host <user@host> (or set OLLAMA_SSH_HOST)",
        )
    username: str | None = None
    host_part = text
    if "@" in text:
        user_raw, host_part = text.split("@", 1)
        username = user_raw.strip() or None
    port = DEFAULT_SSH_PORT
    if ":" in host_part and not host_part.startswith("["):
        host_only, port_raw = host_part.rsplit(":", 1)
        if port_raw.isdigit():
            host_part = host_only
            port = int(port_raw)
    host = host_part.strip()
    if not host:
        raise TunnelProbeError(
            "ssh-unreachable",
            f"invalid SSH host target {raw!r}",
            "pass --ssh-host <[user@]host[:port]>",
        )
    return SshTarget(username=username, host=host, port=port)


def _forwarder_kwargs(spec: TunnelSpec, target: SshTarget) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "ssh_address_or_host": (target.host, target.port),
        "remote_bind_address": spec.remote_bind_address,
        "local_bind_address": spec.local_bind_address,
        "allow_agent": True,
    }
    if target.username:
        kwargs["ssh_username"] = target.username
    if spec.ssh_pkey is not None:
        kwargs["ssh_pkey"] = str(spec.ssh_pkey)
    if spec.ssh_password is not None:
        kwargs["ssh_password"] = spec.ssh_password
    return kwargs


def _classify_tunnel_exception(ssh_host: str, exc: Exception) -> TunnelProbeError:
    if isinstance(exc, sshtunnel.HandlerSSHTunnelForwarderError):
        return TunnelProbeError(
            "tunnel-dead",
            f"SSH port-forwarding handler failed for {ssh_host}: {exc}",
            "verify remote port forwarding is allowed and Ollama is listening on the remote host",
        )
    return TunnelProbeError(
        "ssh-unreachable",
        f"cannot establish SSH tunnel to {ssh_host}: {exc}",
        "verify network/VPN connectivity, SSH config, and key authentication",
    )


class ManagedSshTunnel:
    """Context-managed wrapper around ``sshtunnel.SSHTunnelForwarder``."""

    def __init__(
        self,
        spec: TunnelSpec,
        *,
        forwarder_factory: Callable[..., Any] = sshtunnel.SSHTunnelForwarder,
    ) -> None:
        self._spec = spec
        self._factory = forwarder_factory
        self._forwarder: Any | None = None

    @property
    def local_bind_port(self) -> int | None:
        """Local TCP port allocated by the active forwarder, or None if stopped."""
        if self._forwarder is None:
            return None
        return getattr(self._forwarder, "local_bind_port", None)

    @property
    def is_active(self) -> bool:
        """Return True while the underlying forwarder reports active."""
        return bool(self._forwarder is not None and getattr(self._forwarder, "is_active", False))

    def start(self) -> ManagedSshTunnel:
        """Create and start the SSH tunnel, translating failures to ``TunnelProbeError``."""
        target = parse_ssh_target(self._spec.ssh_host)
        kwargs = _forwarder_kwargs(self._spec, target)
        try:
            forwarder = self._factory(**kwargs)
            forwarder.start()
        except TunnelProbeError:
            raise
        except (
            sshtunnel.BaseSSHTunnelForwarderError,
            paramiko.SSHException,
            OSError,
            ValueError,
        ) as exc:
            raise _classify_tunnel_exception(self._spec.ssh_host, exc) from exc
        self._forwarder = forwarder
        if not self.is_active:
            self.stop()
            raise TunnelProbeError(
                "tunnel-dead",
                f"SSH tunnel to {self._spec.ssh_host} started but is not active",
                f"verify SSH port forwarding to {self._spec.remote_bind_address} on {target.host}",
            )
        return self

    def stop(self) -> None:
        """Stop the underlying forwarder if running (idempotent)."""
        forwarder = self._forwarder
        self._forwarder = None
        if forwarder is not None:
            with contextlib.suppress(Exception):
                forwarder.stop()

    def __enter__(self) -> ManagedSshTunnel:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class SshTunnelAdapter:
    """Verify SSH host reachability and port forwarding via ``sshtunnel``."""

    def __init__(
        self,
        *,
        forwarder_factory: Callable[..., Any] = sshtunnel.SSHTunnelForwarder,
        remote_bind_address: tuple[str, int] = DEFAULT_REMOTE_OLLAMA_BIND,
        ssh_pkey: Path | None = None,
        ssh_password: str | None = None,
    ) -> None:
        self._factory = forwarder_factory
        self._remote_bind_address = remote_bind_address
        self._ssh_pkey = ssh_pkey
        self._ssh_password = ssh_password

    def verify(self, ssh_host: str | None, control_path: Path | None) -> None:
        """Raise :class:`TunnelProbeError` if the SSH host or tunnel cannot be established."""
        if not ssh_host:
            raise TunnelProbeError(
                "ssh-unreachable",
                "no SSH host configured for remote-ollama preflight",
                "pass --ssh-host <user@host> (or set OLLAMA_SSH_HOST)",
            )
        if control_path is not None and not control_path.exists():
            raise TunnelProbeError(
                "tunnel-dead",
                f"ControlMaster socket does not exist: {control_path}",
                "remove --control-path to verify via sshtunnel or re-open the local socket",
            )
        spec = TunnelSpec(
            ssh_host=ssh_host,
            remote_bind_address=self._remote_bind_address,
            ssh_pkey=self._ssh_pkey,
            ssh_password=self._ssh_password,
        )
        with ManagedSshTunnel(spec, forwarder_factory=self._factory):
            return None
