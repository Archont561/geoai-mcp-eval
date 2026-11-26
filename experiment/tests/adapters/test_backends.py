"""Properties of backend profile resolution and HTTP request translation."""

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fakes import make_mock_response
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.adapters import backends

fixture_settings = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
model_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)


@fixture_settings
@given(model=model_names, max_tokens=st.integers(1, 4096))
def test_loaded_profile_preserves_configured_values(
    tmp_path: Path, model: str, max_tokens: int
) -> None:
    path = tmp_path / "experiment.toml"
    path.write_text(
        f'[backends.demo]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "{model}"\n'
        f"max_tokens = {max_tokens}\n",
        encoding="utf-8",
    )
    profiles = backends.load_profiles(path)
    assert set(profiles) == {"demo"}
    assert profiles["demo"].model == model
    assert profiles["demo"].max_tokens == max_tokens


@fixture_settings
@example(secret="secret")
@given(secret=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=30))
def test_sessions_only_include_auth_when_configured(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    profile = backends.BackendProfile(base_url="http://h/v1", model="m", api_key_env="X_TEST_KEY")
    monkeypatch.delenv("X_TEST_KEY", raising=False)
    with pytest.raises(backends.BackendError, match="X_TEST_KEY"):
        backends.build_session(profile)
    monkeypatch.setenv("X_TEST_KEY", secret)
    with backends.build_session(profile) as session:
        assert session.headers["Authorization"] == f"Bearer {secret}"
    anonymous = profile.model_copy(update={"api_key_env": None})
    with backends.build_session(anonymous) as anonymous_session:
        assert "Authorization" not in anonymous_session.headers


@fixture_settings
@example(max_tokens=77, answer="ok")
@given(max_tokens=st.integers(1, 4096), answer=model_names)
def test_chat_request_preserves_parameters_and_response(
    fake_http_session: MagicMock, max_tokens: int, answer: str
) -> None:
    fake_http_session.reset_mock(side_effect=True, return_value=True)
    fake_http_session.post.return_value = make_mock_response(
        200, {"choices": [{"message": {"content": answer}}]}
    )
    profile = backends.BackendProfile(base_url="http://h/v1", model="m", max_tokens=max_tokens)
    payload = backends.chat_completions(
        fake_http_session, profile, [{"role": "user", "content": "hi"}], None
    )
    assert payload["choices"][0]["message"]["content"] == answer
    assert fake_http_session.post.call_args.args[0] == "http://h/v1/chat/completions"
    kwargs = fake_http_session.post.call_args.kwargs
    assert kwargs["json"]["max_tokens"] == max_tokens
    assert kwargs["json"]["temperature"] == 0.0
    assert "options" not in kwargs["json"]
    assert kwargs["timeout"] == httpx.Timeout(
        connect=profile.connect_timeout_s,
        read=profile.read_timeout_s,
        write=profile.read_timeout_s,
        pool=profile.connect_timeout_s,
    )


@fixture_settings
@given(error=st.sampled_from([httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout]))
def test_chat_transport_errors_are_classified(fake_http_session: MagicMock, error: type) -> None:
    fake_http_session.reset_mock(side_effect=True, return_value=True)
    fake_http_session.post.side_effect = error("failed")
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == ("timeout" if error is httpx.ReadTimeout else "connection")


@fixture_settings
@example(status=429, retry=17)
@example(status=503, retry=17)
@given(status=st.integers(400, 599), retry=st.integers(0, 1000))
def test_chat_http_errors_are_classified(
    fake_http_session: MagicMock, status: int, retry: int
) -> None:
    fake_http_session.reset_mock(side_effect=True, return_value=True)
    fake_http_session.post.return_value = make_mock_response(
        status, text="failed", headers={"Retry-After": str(retry)}
    )
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == ("rate-limit" if status == 429 else f"http-{status}")
    if status == 429:
        assert str(retry) in str(excinfo.value)


@fixture_settings
@given(response=model_names)
def test_chat_invalid_json_is_classified(fake_http_session: MagicMock, response: str) -> None:
    fake_http_session.reset_mock(side_effect=True, return_value=True)
    fake_http_session.post.return_value = make_mock_response(200, ValueError("bad"), text=response)
    profile = backends.BackendProfile(base_url="http://h/v1", model="m")
    with pytest.raises(backends.BackendError) as excinfo:
        backends.chat_completions(fake_http_session, profile, [])
    assert excinfo.value.error_class == "invalid-response"
    assert response in str(excinfo.value)


@fixture_settings
@example(model="qwen2.5:3b", digest="abc123", latest=False)
@given(model=model_names, digest=model_names, latest=st.booleans())
def test_model_digest_matches_exact_or_latest(
    fake_http_session: MagicMock, model: str, digest: str, latest: bool
) -> None:
    fake_http_session.reset_mock(side_effect=True, return_value=True)
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", model)
    model_entry = {
        "model" if latest else "name": model + (":latest" if latest else ""),
        "digest": "sha256:" + digest,
    }
    fake_http_session.get.return_value = make_mock_response(200, {"models": [model_entry]})
    assert backends.resolve_model_digest(fake_http_session, profile) == "sha256:" + digest
