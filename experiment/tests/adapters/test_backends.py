"""Unit tests for ``experiment.adapters.backends``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fakes import make_mock_response

from experiment.adapters import backends


@pytest.fixture
def demo_backends_toml(tmp_path: Path) -> Path:
    path = tmp_path / "experiment.toml"
    path.write_text(
        '[backends.demo]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "m"\nmax_tokens = 128\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def local_and_remote_toml(tmp_path: Path) -> Path:
    path = tmp_path / "experiment.toml"
    path.write_text(
        '[backends.local]\nbase_url = "http://from-file/v1"\nmodel = "file-model"\n'
        '[backends.free-open]\nbase_url = "http://remote/v1"\nmodel = "m"\n'
        'api_key_env = "X_TEST_KEY"\n',
        encoding="utf-8",
    )
    return path


def test_load_profiles_roundtrip(demo_backends_toml: Path) -> None:
    profiles = backends.load_profiles(demo_backends_toml)
    assert set(profiles) == {"demo"}
    assert profiles["demo"].max_tokens == 128


def test_load_profiles_missing_file(tmp_path: Path) -> None:
    with pytest.raises(backends.BackendError, match="config"):
        backends.load_profiles(tmp_path / "nope.toml")


def test_load_profiles_bad_toml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[backends\n", encoding="utf-8")
    with pytest.raises(backends.BackendError, match="config"):
        backends.load_profiles(bad)


def test_resolve_unknown_backend_names_known(demo_backends_toml: Path) -> None:
    with pytest.raises(backends.BackendError, match="demo"):
        backends.resolve_profile("nope", path=demo_backends_toml)


def test_resolve_host_override_wins(local_and_remote_toml: Path) -> None:
    profile = backends.resolve_profile("local", host="http://flag:1234", path=local_and_remote_toml)
    assert str(profile.base_url).rstrip("/") == "http://flag:1234"


def test_resolve_model_override_wins(local_and_remote_toml: Path) -> None:
    profile = backends.resolve_profile("local", model="flag-model", path=local_and_remote_toml)
    assert profile.model == "flag-model"


def test_ollama_host_env_applies_to_local_only(
    local_and_remote_toml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://env:11434")
    monkeypatch.setenv("X_TEST_KEY", "k")
    assert (
        str(backends.resolve_profile("local", path=local_and_remote_toml).base_url)
        .rstrip("/")
        .startswith("http://env:11434")
    )
    assert (
        str(backends.resolve_profile("free-open", path=local_and_remote_toml).base_url).rstrip("/")
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


def test_chat_completions_success(fake_http_session: MagicMock) -> None:
    fake_http_session.post.return_value = make_mock_response(
        200, {"choices": [{"message": {"content": "ok"}}]}
    )
    profile = backends.BackendProfile(base_url="http://h/v1", model="m", max_tokens=77)
    payload = backends.chat_completions(
        fake_http_session, profile, [{"role": "user", "content": "hi"}], None
    )
    assert payload["choices"][0]["message"]["content"] == "ok"
    url = fake_http_session.post.call_args.args[0]
    kwargs = fake_http_session.post.call_args.kwargs
    assert url == "http://h/v1/chat/completions"
    assert kwargs["json"]["max_tokens"] == 77
    assert kwargs["json"]["temperature"] == 0.0
    assert "options" not in kwargs["json"]
    assert kwargs["timeout"] == httpx.Timeout(
        connect=profile.connect_timeout_s,
        read=profile.read_timeout_s,
        write=profile.read_timeout_s,
        pool=profile.connect_timeout_s,
    )


def test_chat_completions_connection_error(fake_http_session: MagicMock) -> None:
    fake_http_session.post.side_effect = httpx.ConnectError("refused")
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == "connection"


def test_chat_completions_read_timeout(fake_http_session: MagicMock) -> None:
    fake_http_session.post.side_effect = httpx.ReadTimeout("slow")
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == "timeout"


def test_chat_completions_rate_limit_includes_retry_after(fake_http_session: MagicMock) -> None:
    fake_http_session.post.return_value = make_mock_response(
        429, text="slow down", headers={"Retry-After": "17"}
    )
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == "rate-limit"
    assert "17" in str(excinfo.value)


def test_chat_completions_http_error_class(fake_http_session: MagicMock) -> None:
    fake_http_session.post.return_value = make_mock_response(503, text="down")
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == "http-503"


def test_chat_completions_invalid_json(fake_http_session: MagicMock) -> None:
    fake_http_session.post.return_value = make_mock_response(200, ValueError("bad"), text="<html>")
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == "invalid-response"


def test_resolve_model_digest_matches_exact_and_latest_and_handles_failures(
    fake_http_session: MagicMock,
) -> None:
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")

    fake_http_session.get.return_value = make_mock_response(
        200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:abc123"}]}
    )
    assert backends.resolve_model_digest(fake_http_session, profile) == "sha256:abc123"

    untagged = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5")
    fake_http_session.get.return_value = make_mock_response(
        200, {"models": [{"model": "qwen2.5:latest", "digest": "sha256:def456"}]}
    )
    assert backends.resolve_model_digest(fake_http_session, untagged) == "sha256:def456"

    fake_http_session.get.return_value = make_mock_response(500)
    assert backends.resolve_model_digest(fake_http_session, profile) is None

    fake_http_session.get.return_value = make_mock_response(200, ValueError("not json"))
    assert backends.resolve_model_digest(fake_http_session, profile) is None

    fake_http_session.get.side_effect = httpx.ConnectError("down")
    assert backends.resolve_model_digest(fake_http_session, profile) is None
