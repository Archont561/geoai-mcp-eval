"""Unit tests for ``experiment.domain.backend``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.backend import (
    BackendCheckExitCode,
    BackendError,
    BackendProbeErrorKind,
    BackendProfile,
    RetryableHttpStatus,
    TunnelErrorKind,
    normalize_host,
)


def test_profile_defaults() -> None:
    profile = BackendProfile(base_url="http://127.0.0.1:11434", model="m")
    assert profile.max_tokens == 2048
    assert profile.temperature == 0.0
    assert profile.retries == 3
    assert profile.timeout == (5.0, 300.0)
    assert profile.chat_url == "http://127.0.0.1:11434/v1/chat/completions"


def test_chat_url_keeps_existing_v1_suffix() -> None:
    profile = BackendProfile(base_url="http://h:11434/v1/", model="m")
    assert profile.chat_url == "http://h:11434/v1/chat/completions"


def test_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError):
        BackendProfile(base_url="http://h", model="m", bogus=1)  # type: ignore[call-arg]


@given(
    temperature=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    max_tokens=st.integers(min_value=1, max_value=32768),
    retries=st.integers(min_value=0, max_value=10),
    model=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789:.-_/", min_size=1, max_size=32),
)
def test_backend_profile_roundtrips_valid_parameters(
    temperature: float, max_tokens: int, retries: int, model: str
) -> None:
    profile = BackendProfile(
        base_url="http://127.0.0.1:11434",
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        retries=retries,
    )
    assert BackendProfile.model_validate_json(profile.model_dump_json()) == profile
    assert profile.chat_url.endswith("/v1/chat/completions")


@given(
    bad_temp=st.one_of(
        st.floats(max_value=-0.01, allow_nan=False, allow_infinity=False),
        st.floats(min_value=2.01, allow_nan=False, allow_infinity=False),
    )
)
def test_invalid_temperature_rejected(bad_temp: float) -> None:
    with pytest.raises(ValidationError):
        BackendProfile(base_url="http://h", model="m", temperature=bad_temp)


@given(
    host=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.:-", min_size=1, max_size=24),
    slashes=st.integers(min_value=0, max_value=4),
)
def test_normalize_host_strips_trailing_slashes_idempotently(host: str, slashes: int) -> None:
    normalized = normalize_host(host + "/" * slashes)
    assert not normalized.endswith("/")
    assert normalize_host(normalized) == normalized


def test_backend_error_formats_message() -> None:
    err = BackendError("transport", "boom")
    assert "boom" in str(err)


@given(kind=st.sampled_from(list(BackendProbeErrorKind)))
def test_backend_probe_error_kind_maps_to_nonzero_exit_code(kind: BackendProbeErrorKind) -> None:
    code = kind.exit_code()
    assert isinstance(code, BackendCheckExitCode)
    assert code is BackendCheckExitCode.from_error_kind(kind)
    assert code >= 10
    assert BackendCheckExitCode.from_error_kind("unrecognized-kind") is (
        BackendCheckExitCode.COMPLETION_REJECTED
    )


@given(tunnel_kind=st.sampled_from(list(TunnelErrorKind)))
def test_tunnel_error_kinds_are_valid_backend_probe_error_kinds(
    tunnel_kind: TunnelErrorKind,
) -> None:
    assert BackendProbeErrorKind(tunnel_kind.value).exit_code() in (
        BackendCheckExitCode.SSH_UNREACHABLE,
        BackendCheckExitCode.TUNNEL_DEAD,
    )


@given(status_code=st.integers(min_value=100, max_value=599))
def test_retryable_http_status_contains_matches_documented_transient_codes(
    status_code: int,
) -> None:
    expected = status_code in {429, 500, 502, 503, 504}
    assert RetryableHttpStatus.contains(status_code) is expected
