"""Unit tests for ``experiment.adapters.openrouter``."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from openrouter.errors import OpenRouterError

from experiment.adapters import openrouter as openrouter_adapter
from experiment.domain.backend import BackendError, BackendProfile


@pytest.fixture
def rate_limit_error() -> OpenRouterError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(429, text="rate limited", headers={"Retry-After": "1"}, request=req)
    return OpenRouterError("HTTP 429: rate limited", raw_response=resp, body="rate limited")


def test_openrouter_chat_gateway_tool_calls_usage_retries_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
    rate_limit_error: OpenRouterError,
) -> None:
    secret = "sk-or-v1-super-secret-value"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    assert openrouter_adapter.is_openrouter_profile(openrouter_profile) is True

    fake_openrouter_sdk_client.chat.send.side_effect = [
        rate_limit_error,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tc_1",
                                "type": "function",
                                "function": {"name": "relate_de9im", "arguments": '{"a": 1}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125},
        },
        {"choices": [{"message": {"role": "assistant", "content": "done"}}], "usage": None},
    ]

    gw = openrouter_adapter.OpenRouterChatGateway(
        openrouter_profile, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    reply1 = gw.complete([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert fake_openrouter_sdk_client.chat.send.call_count == 2
    assert reply1["usage"] == {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125}
    turn = gw.parse_turn(reply1)
    assert turn.tool_calls[0].call_id == "tc_1"
    assert turn.tool_calls[0].arguments == {"a": 1}

    reply2 = gw.complete([{"role": "user", "content": "finish"}])
    assert "usage" not in reply2

    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    body = f"invalid key {secret}"
    auth_err = OpenRouterError(
        f"HTTP 401: {body}", raw_response=httpx.Response(401, text=body, request=req), body=body
    )
    fake_openrouter_sdk_client.chat.send.reset_mock()
    fake_openrouter_sdk_client.chat.send.side_effect = auth_err
    gw._secret = secret
    with pytest.raises(BackendError) as err401:
        gw.complete([{"role": "user", "content": "hi"}])
    assert err401.value.error_class == "http-401"
    assert secret not in str(err401.value)
    assert "[REDACTED]" in str(err401.value)
    assert fake_openrouter_sdk_client.chat.send.call_count == 1


@pytest.mark.parametrize(
    ("status", "body", "for_comp", "expected_kind"),
    [
        (401, "unauthorized", False, "auth-error"),
        (400, "context_length exceeded", True, "token-limit"),
        (429, "quota", True, "token-limit"),
        (404, "missing model", False, "client-error"),
        (502, "bad gateway", False, "tunnel-dead"),
    ],
)
def test_openrouter_classify_probe_error(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    status: int,
    body: str,
    for_comp: bool,
    expected_kind: str,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = openrouter_profile.model_copy(update={"retries": 0})
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    err = OpenRouterError(
        f"HTTP {status}: {body}",
        raw_response=httpx.Response(status, text=body, request=req),
        body=body,
    )
    kind, _detail, _hint = openrouter_adapter.classify_probe_error(
        err, or_prof, "sk-or-test-key", for_completion=for_comp
    )
    assert kind == expected_kind


@pytest.mark.parametrize(
    ("exc_obj", "expected_cls"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connection"),
        (httpx.ProtocolError("bad proto"), "transport"),
    ],
)
def test_openrouter_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
    exc_obj: Exception,
    expected_cls: str,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = openrouter_profile.model_copy(update={"retries": 0})
    fake_openrouter_sdk_client.chat.send.side_effect = exc_obj
    gw = openrouter_adapter.OpenRouterChatGateway(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(BackendError) as err_chat:
        gw.complete([{"role": "user", "content": "hi"}])
    assert err_chat.value.error_class == expected_cls
