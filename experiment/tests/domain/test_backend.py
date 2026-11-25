"""Unit tests for ``experiment.domain.backend``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.backend import BackendError, BackendProfile, normalize_host


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


def test_invalid_temperature_rejected() -> None:
    with pytest.raises(ValidationError):
        BackendProfile(base_url="http://h", model="m", temperature=3.5)


def test_normalize_host_and_error() -> None:
    assert normalize_host("127.0.0.1:11434/") == "127.0.0.1:11434"
    assert normalize_host("https://api.example.com/") == "https://api.example.com"
    err = BackendError("transport", "boom")
    assert "boom" in str(err)
