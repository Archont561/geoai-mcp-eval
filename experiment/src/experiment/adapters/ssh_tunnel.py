"""SSH host reachability and ControlMaster tunnel verification adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from experiment.adapters import subprocess_runner

TunnelErrorKind = Literal["ssh-unreachable", "tunnel-dead"]


class TunnelProbeError(RuntimeError):
    """Structured SSH/ControlMaster failure carrying semantic kind and remediation hint."""

    def __init__(self, kind: TunnelErrorKind, detail: str, hint: str) -> None:
        self.kind = kind
        self.detail = detail
        self.hint = hint
        super().__init__(f"[{kind}] {detail}. Next step: {hint}")


def default_run_cmd(cmd: list[str], *, timeout: float) -> subprocess_runner.CommandResult:
    """Default subprocess runner for SSH and ControlMaster probes."""
    return subprocess_runner.run_command(cmd, timeout=timeout)


def _format_stderr(res: Any) -> str:
    return (getattr(res, "stderr", "") or "").strip() or f"exit {res.returncode}"


def _probe_ssh_host(ssh_host: str, run_cmd: Callable[..., Any]) -> None:
    probe_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ssh_host, "true"]
    try:
        ssh_res = run_cmd(probe_cmd, timeout=10.0)
    except (OSError, subprocess_runner.CommandTimeoutError, TimeoutError) as exc:
        raise TunnelProbeError(
            "ssh-unreachable",
            f"cannot reach SSH host {ssh_host}: {exc}",
            "verify network/VPN connectivity, SSH config, and key authentication",
        ) from exc
    if ssh_res.returncode != 0:
        raise TunnelProbeError(
            "ssh-unreachable",
            f"SSH host {ssh_host} unreachable ({_format_stderr(ssh_res)})",
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
        raise TunnelProbeError(
            "tunnel-dead",
            f"SSH ControlMaster check failed for {ssh_host}: {exc}",
            "restart the ControlMaster tunnel before running the experiment",
        ) from exc
    if ctrl_res.returncode != 0:
        raise TunnelProbeError(
            "tunnel-dead",
            f"SSH ControlMaster tunnel is not running ({_format_stderr(ctrl_res)})",
            f"re-establish the ControlMaster tunnel to {ssh_host}",
        )


class SshTunnelAdapter:
    """Verify SSH host reachability and an active ControlMaster socket."""

    def __init__(self, *, run_cmd: Callable[..., Any] = default_run_cmd) -> None:
        self._run_cmd = run_cmd

    def verify(self, ssh_host: str | None, control_path: Path | None) -> None:
        """Raise :class:`TunnelProbeError` if the SSH host or ControlMaster tunnel is down."""
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
                f"open the SSH tunnel with `ssh -M -S {control_path} -fNT -L ... {ssh_host}`",
            )
        _probe_ssh_host(ssh_host, self._run_cmd)
        _probe_control_tunnel(ssh_host, control_path, self._run_cmd)
