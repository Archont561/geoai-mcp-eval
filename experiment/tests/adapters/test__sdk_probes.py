"""Unit tests for ``experiment.adapters._sdk_probes``."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import ollama as ollama_sdk
import pytest
from openrouter.errors import OpenRouterError

from experiment.adapters import _sdk_probes, backend_probe
from experiment.domain.backend import BackendProfile


@pytest.fixture
def forbidden_openrouter_error() -> OpenRouterError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(403, text="forbidden", request=req)
    return OpenRouterError("HTTP 403: forbidden", raw_response=resp, body="forbidden")


def test_ollama_backend_probe_sdk_success_and_error_kinds(
    ollama_profile: BackendProfile,
    fake_ollama_sdk_client: MagicMock,
) -> None:
    profile = ollama_profile.model_copy(update={"retries": 1})
    fake_ollama_sdk_client.list.side_effect = [
        ollama_sdk.ResponseError("transient", status_code=503),
        {"models": [{"model": "qwen2.5:3b", "digest": "sha256:aaa111"}]},
        {"models": [{"model": "qwen2.5:3b", "digest": "sha256:aaa111"}]},
    ]
    fake_ollama_sdk_client.chat.return_value = {"message": {"role": "assistant", "content": "OK"}}

    probe = _sdk_probes.OllamaBackendProbe(
        profile, client=fake_ollama_sdk_client, sleep=lambda _s: None
    )
    assert probe.list_model_ids() == {"qwen2.5:3b"}
    assert probe.resolve_model_digest() == "sha256:aaa111"
    probe.verify_tiny_completion(max_tokens=8)
    assert fake_ollama_sdk_client.list.call_count == 3

    auth_client = MagicMock(name="ollama_auth_client")
    auth_client.list.side_effect = ollama_sdk.ResponseError("denied", status_code=401)
    auth_probe = _sdk_probes.OllamaBackendProbe(profile, client=auth_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_auth:
        auth_probe.list_model_ids()
    assert e_auth.value.kind == "auth-error"
    assert auth_client.list.call_count == 1

    tok_client = MagicMock(name="ollama_tok_client")
    tok_client.chat.side_effect = ollama_sdk.ResponseError(
        "context length exceeded", status_code=400
    )
    tok_probe = _sdk_probes.OllamaBackendProbe(profile, client=tok_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_tok:
        tok_probe.verify_tiny_completion(max_tokens=8)
    assert e_tok.value.kind == "token-limit"


def test_openrouter_and_ollama_probe_error_paths_and_close(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    ollama_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
    fake_ollama_sdk_client: MagicMock,
    forbidden_openrouter_error: OpenRouterError,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = openrouter_profile.model_copy(update={"retries": 0})
    ol_prof = ollama_profile.model_copy(update={"retries": 0})

    for err, expected_kind in [
        (forbidden_openrouter_error, "auth-error"),
        (httpx.ConnectError("offline"), "tunnel-dead"),
    ]:
        fake_openrouter_sdk_client.models.list.side_effect = err
        probe = _sdk_probes.OpenRouterBackendProbe(
            or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
        )
        with pytest.raises(backend_probe.BackendProbeError) as exc_info:
            probe.list_model_ids()
        assert exc_info.value.kind == expected_kind

    fake_openrouter_sdk_client.chat.send.return_value = {"choices": []}
    empty_or = _sdk_probes.OpenRouterBackendProbe(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_empty:
        empty_or.verify_tiny_completion(max_tokens=8)
    assert e_empty.value.kind == "completion-rejected"

    fake_ollama_sdk_client.list.side_effect = httpx.ConnectError("down")
    conn_ol = _sdk_probes.OllamaBackendProbe(
        ol_prof, client=fake_ollama_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_ol_conn:
        conn_ol.list_model_ids()
    assert e_ol_conn.value.kind == "tunnel-dead"

    fake_ollama_sdk_client.chat.return_value = {"message": {}}
    empty_ol = _sdk_probes.OllamaBackendProbe(
        ol_prof, client=fake_ollama_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_ol_empty:
        empty_ol.verify_tiny_completion(max_tokens=8)
    assert e_ol_empty.value.kind == "completion-rejected"

    p_close = _sdk_probes.OpenRouterBackendProbe(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    p_close._owns_client = True
    p_close.close()
    fake_openrouter_sdk_client.__exit__.assert_called_once()
