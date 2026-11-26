"""Unit tests for ``experiment.adapters.ssh_tunnel``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters.ssh_tunnel import (
    SshTarget,
    TunnelProbeError,
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


@given(host=SSH_IDENT)
def test_target_without_port_uses_standard_ssh_port(host: str) -> None:
    target = parse_ssh_target(host)
    assert (target.username, target.host, target.port) == (None, host, 22)


@given(blank=st.text(alphabet=" \t\n", max_size=20))
def test_blank_target_is_unreachable(blank: str) -> None:
    with pytest.raises(TunnelProbeError) as error:
        parse_ssh_target(blank)
    assert error.value.kind == "ssh-unreachable"


@given(port=st.one_of(st.integers(max_value=0), st.integers(min_value=65536)))
def test_target_rejects_out_of_range_ports(port: int) -> None:
    with pytest.raises(ValidationError):
        SshTarget(username=None, host="gpu", port=port)
