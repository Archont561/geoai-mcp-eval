"""Unit tests for ``experiment.adapters.ssh_tunnel``."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import paramiko
import pytest
import sshtunnel
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters.ssh_tunnel import (
    ManagedSshTunnel,
    SshTarget,
    SshTunnelAdapter,
    TunnelProbeError,
    TunnelSpec,
    parse_ssh_target,
)

SSH_IDENT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.", min_size=1, max_size=16)


@given(
    username=st.one_of(st.none(), SSH_IDENT),
    host=SSH_IDENT,
    port=st.integers(min_value=1, max_value=65535),
)
def test_parse_ssh_target_roundtrips_arbitrary_valid_specs(
    username: str | None, host: str, port: int
) -> None:
    raw = f"{username}@{host}:{port}" if username is not None else f"{host}:{port}"
    target = parse_ssh_target(raw)
    assert target == SshTarget(username=username, host=host, port=port)
    assert SshTarget.model_validate_json(target.model_dump_json()) == target


def test_sshtunnel_target_parsing_and_managed_lifecycle(
    fake_ssh_forwarder: MagicMock,
) -> None:
    simple = parse_ssh_target("gpu-box")
    assert (simple.username, simple.host, simple.port) == (None, "gpu-box", 22)
    with pytest.raises(TunnelProbeError) as empty_err:
        parse_ssh_target("   ")
    assert empty_err.value.kind == "ssh-unreachable"
    with pytest.raises(ValidationError):
        SshTarget(username=None, host="gpu", port=0)

    captured: dict[str, Any] = {}
    fake_ssh_forwarder.local_bind_port = 41234

    def factory(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return fake_ssh_forwarder

    spec = TunnelSpec(ssh_host="alice@gpu.example.org:2222", ssh_password="pw")
    with ManagedSshTunnel(spec, forwarder_factory=factory) as tunnel:
        assert tunnel.is_active is True
        assert tunnel.local_bind_port == 41234
        assert captured["ssh_address_or_host"] == ("gpu.example.org", 2222)
        assert captured["ssh_username"] == "alice"
    fake_ssh_forwarder.start.assert_called_once()
    fake_ssh_forwarder.stop.assert_called_once()
    assert tunnel.local_bind_port is None


def test_sshtunnel_error_classification_and_teardown(
    fake_ssh_forwarder: MagicMock,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
) -> None:
    fake_ssh_forwarder.start.side_effect = sshtunnel.HandlerSSHTunnelForwarderError("bind refused")
    with pytest.raises(TunnelProbeError) as handler_err:
        fake_ssh_tunnel_adapter.verify("gpu-box", None)
    assert handler_err.value.kind == "tunnel-dead"

    fake_ssh_forwarder.start.side_effect = paramiko.SSHException("auth failed")
    with pytest.raises(TunnelProbeError) as auth_err:
        fake_ssh_tunnel_adapter.verify("gpu-box", None)
    assert auth_err.value.kind == "ssh-unreachable"

    fake_ssh_forwarder.start.side_effect = None
    fake_ssh_forwarder.is_active = False
    with pytest.raises(TunnelProbeError) as dead_err:
        fake_ssh_tunnel_adapter.verify("gpu-box", None)
    assert dead_err.value.kind == "tunnel-dead"
    fake_ssh_forwarder.stop.assert_called()
