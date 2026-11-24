"""Unit tests for the TOML-backed chat completion profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
from pydantic import ValidationError

from experiment.adapters import backends


def _write_toml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_profile_defaults() -> None:
    profile = backends.BackendProfile(base_url="http://127.0.0.1:11434", model="m")
    assert profile.max_tokens == 2048
    assert profile.temperature == 0.0
    assert profile.retries == 3
    assert profile.timeout == (5.0, 300.0)
    assert profile.chat_url == "http://127.0.0.1:11434/v1/chat/completions"


def test_chat_url_keeps_existing_v1_suffix() -> None:
    profile = backends.BackendProfile(base_url="http://h:11434/v1/", model="m")
    assert profile.chat_url == "http://h:11434/v1/chat/completions"


def test_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError):
        backends.BackendProfile(base_url="http://h", model="m", bogus=1)  # type: ignore[call-arg]


def test_invalid_temperature_rejected() -> None:
    with pytest.raises(ValidationError):
        backends.BackendProfile(base_url="http://h", model="m", temperature=3.5)


def test_load_profiles_roundtrip(tmp_path: Path) -> None:
    toml = _write_toml(
        tmp_path / "backends.toml",
        '[backends.demo]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "m"\nmax_tokens = 128\n',
    )
    profiles = backends.load_profiles(toml)
    assert set(profiles) == {"demo"}
    assert profiles["demo"].max_tokens == 128


def test_load_profiles_missing_file(tmp_path: Path) -> None:
    with pytest.raises(backends.BackendError, match="config"):
        backends.load_profiles(tmp_path / "nope.toml")


def test_load_profiles_bad_toml(tmp_path: Path) -> None:
    toml = _write_toml(tmp_path / "bad.toml", "[backends\n")
    with pytest.raises(backends.BackendError, match="config"):
        backends.load_profiles(toml)


def test_resolve_unknown_backend_names_known(tmp_path: Path) -> None:
    toml = _write_toml(
        tmp_path / "backends.toml",
        '[backends.demo]\nbase_url = "http://h/v1"\nmodel = "m"\n',
    )
    with pytest.raises(backends.BackendError, match="demo"):
        backends.resolve_profile("nope", path=toml)


def test_resolve_host_override_wins(tmp_path: Path) -> None:
    toml = _write_toml(
        tmp_path / "backends.toml",
        '[backends.local]\nbase_url = "http://from-file/v1"\nmodel = "file-model"\n',
    )
    profile = backends.resolve_profile("local", host="http://flag:1234", path=toml)
    assert str(profile.base_url).rstrip("/") == "http://flag:1234"


def test_resolve_model_override_wins(tmp_path: Path) -> None:
    toml = _write_toml(
        tmp_path / "backends.toml",
        '[backends.local]\nbase_url = "http://from-file/v1"\nmodel = "file-model"\n',
    )
    profile = backends.resolve_profile("local", model="flag-model", path=toml)
    assert profile.model == "flag-model"


def test_ollama_host_env_applies_to_local_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = _write_toml(
        tmp_path / "backends.toml",
        '[backends.local]\nbase_url = "http://from-file/v1"\nmodel = "m"\n'
        '[backends.free-open]\nbase_url = "http://remote/v1"\nmodel = "m"\n'
        'api_key_env = "X_TEST_KEY"\n',
    )
    monkeypatch.setenv("OLLAMA_HOST", "http://env:11434")
    monkeypatch.setenv("X_TEST_KEY", "k")
    assert (
        str(backends.resolve_profile("local", path=toml).base_url)
        .rstrip("/")
        .startswith("http://env:11434")
    )
    assert (
        str(backends.resolve_profile("free-open", path=toml).base_url).rstrip("/")
        == "http://remote/v1"
    )


def test_resolve_default_when_local_missing_everywhere(tmp_path: Path) -> None:
    profile = backends.resolve_profile("local", path=tmp_path / "absent.toml")
    assert str(profile.base_url).rstrip("/") == "http://127.0.0.1:11434"
    assert profile.model == "qwen2.5-coder:0.5b"


def test_build_session_requires_named_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_MISSING_KEY", raising=False)
    profile = backends.BackendProfile(
        base_url="http://h/v1", model="m", api_key_env="X_MISSING_KEY"
    )
    with pytest.raises(backends.BackendError, match="X_MISSING_KEY"):
        backends.build_session(profile)


def test_build_session_sets_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_PRESENT_KEY", "secret")
    profile = backends.BackendProfile(
        base_url="http://h/v1", model="m", api_key_env="X_PRESENT_KEY"
    )
    with backends.build_session(profile) as session:
        assert session.headers["Authorization"] == "Bearer secret"


def test_build_session_without_key_has_no_auth() -> None:
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with backends.build_session(profile) as session:
        assert "Authorization" not in session.headers


class _FakeResponse:
    def __init__(self, status_code: int, payload: object = None, text: str = "", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")
        self.headers = headers or {}

    def json(self) -> object:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


def _post_stub(monkeypatch: pytest.MonkeyPatch, stub):
    session = requests.Session()
    monkeypatch.setattr(session, "post", stub)
    return session


def test_chat_completions_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def stub(url, json=None, timeout=None, **_kwargs):
        captured.update(url=url, body=json, timeout=timeout)
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    session = _post_stub(monkeypatch, stub)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m", max_tokens=77)
    payload = backends.chat_completions(session, profile, [{"role": "user", "content": "hi"}], None)
    assert payload["choices"][0]["message"]["content"] == "ok"
    assert captured["url"] == "http://h/v1/chat/completions"
    assert captured["body"]["max_tokens"] == 77
    assert captured["body"]["temperature"] == 0.0
    assert "options" not in captured["body"]
    assert captured["timeout"] == profile.timeout


def test_chat_completions_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def stub(*_a, **_k):
        raise requests.exceptions.ConnectionError("refused")

    session = _post_stub(monkeypatch, stub)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(session, profile, [])
    assert excinfo.value.error_class == "connection"


def test_chat_completions_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def stub(*_a, **_k):
        raise requests.exceptions.ReadTimeout("slow")

    session = _post_stub(monkeypatch, stub)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(session, profile, [])
    assert excinfo.value.error_class == "timeout"


def test_chat_completions_rate_limit_includes_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub(*_a, **_k):
        return _FakeResponse(429, text="slow down", headers={"Retry-After": "17"})

    session = _post_stub(monkeypatch, stub)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(session, profile, [])
    assert excinfo.value.error_class == "rate-limit"
    assert "17" in str(excinfo.value)


def test_chat_completions_http_error_class(monkeypatch: pytest.MonkeyPatch) -> None:
    def stub(*_a, **_k):
        return _FakeResponse(503, text="down")

    session = _post_stub(monkeypatch, stub)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(session, profile, [])
    assert excinfo.value.error_class == "http-503"


def test_chat_completions_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def stub(*_a, **_k):
        return _FakeResponse(200, ValueError("bad"), text="<html>")

    session = _post_stub(monkeypatch, stub)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(session, profile, [])
    assert excinfo.value.error_class == "invalid-response"
