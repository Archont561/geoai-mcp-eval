"""Unit tests for ``experiment.adapters.ssh_tunnel``."""

from __future__ import annotations

from typing import Any

import paramiko
import pytest
import sshtunnel
from pydantic import ValidationError

from experiment.adapters.ssh_tunnel import (
    ManagedSshTunnel,
    SshTarget,
    SshTunnelAdapter,
    TunnelProbeError,
    TunnelSpec,
    parse_ssh_target,
)


class _RecordingForwarder:
    def __init__(
        self,
        *,
        active: bool = True,
        port: int = 44556,
        start_exc: Exception | None = None,
    ) -> None:
        self.is_active = active
        self.local_bind_port = port
        self._start_exc = start_exc
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True
        if self._start_exc is not None:
            raise self._start_exc

    def stop(self) -> None:
        self.stopped = True
        self.is_active = False


def test_sshtunnel_target_parsing_and_managed_lifecycle() -> None:
    target = parse_ssh_target("alice@gpu.example.org:2222")
    assert (target.username, target.host, target.port) == ("alice", "gpu.example.org", 2222)
    assert SshTarget.model_validate_json(target.model_dump_json()) == target
    simple = parse_ssh_target("gpu-box")
    assert (simple.username, simple.host, simple.port) == (None, "gpu-box", 22)
    with pytest.raises(TunnelProbeError) as empty_err:
        parse_ssh_target("   ")
    assert empty_err.value.kind == "ssh-unreachable"
    with pytest.raises(ValidationError):
        SshTarget(username=None, host="gpu", port=0)

    captured: dict[str, Any] = {}
    fwd = _RecordingForwarder(active=True, port=41234)

    def factory(**kwargs: Any) -> _RecordingForwarder:
        captured.update(kwargs)
        return fwd

    spec = TunnelSpec(ssh_host="alice@gpu.example.org:2222", ssh_password="pw")
    with ManagedSshTunnel(spec, forwarder_factory=factory) as tunnel:
        assert tunnel.is_active is True
        assert tunnel.local_bind_port == 41234
        assert captured["ssh_address_or_host"] == ("gpu.example.org", 2222)
        assert captured["ssh_username"] == "alice"
    assert fwd.started is True
    assert fwd.stopped is True
    assert tunnel.local_bind_port is None


def test_sshtunnel_error_classification_and_teardown() -> None:
    with pytest.raises(TunnelProbeError) as handler_err:
        SshTunnelAdapter(
            forwarder_factory=lambda **_kw: _RecordingForwarder(
                start_exc=sshtunnel.HandlerSSHTunnelForwarderError("bind refused")
            )
        ).verify("gpu-box", None)
    assert handler_err.value.kind == "tunnel-dead"

    with pytest.raises(TunnelProbeError) as auth_err:
        SshTunnelAdapter(
            forwarder_factory=lambda **_kw: _RecordingForwarder(
                start_exc=paramiko.SSHException("auth failed")
            )
        ).verify("gpu-box", None)
    assert auth_err.value.kind == "ssh-unreachable"

    inactive = _RecordingForwarder(active=False)
    with pytest.raises(TunnelProbeError) as dead_err:
        SshTunnelAdapter(forwarder_factory=lambda **_kw: inactive).verify("gpu-box", None)
    assert dead_err.value.kind == "tunnel-dead"
    assert inactive.stopped is True
