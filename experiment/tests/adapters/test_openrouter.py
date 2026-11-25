"""Unit tests for ``experiment.adapters.openrouter``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openrouter.errors import OpenRouterError

from experiment.adapters import openrouter as openrouter_adapter
from experiment.domain.backend import BackendError, BackendProfile


def _openrouter_error(
    status: int, body: str, headers: dict[str, str] | None = None
) -> OpenRouterError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(status, text=body, headers=headers, request=req)
    return OpenRouterError(f"HTTP {status}: {body}", raw_response=resp, body=body)


class _FakeOpenRouterSdkClient:
    def __init__(self, *, chat_responses: list[Any] | None = None) -> None:
        self._chat_queue = list(chat_responses or [])
        self.chat_calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(send=self._send)

    def _send(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        item = self._chat_queue.pop(0) if len(self._chat_queue) > 1 else self._chat_queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _or_profile(retries: int = 2) -> BackendProfile:
    return BackendProfile(
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen-2.5-coder-32b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
        retries=retries,
    )


def test_openrouter_chat_gateway_tool_calls_usage_retries_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-or-v1-super-secret-value"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    profile = _or_profile(retries=2)
    assert openrouter_adapter.is_openrouter_profile(profile) is True

    fake = _FakeOpenRouterSdkClient(
        chat_responses=[
            _openrouter_error(429, "rate limited", headers={"Retry-After": "1"}),
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
                                    "function": {
                                        "name": "relate_de9im",
                                        "arguments": '{"a": 1}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125},
            },
            {
                "choices": [{"message": {"role": "assistant", "content": "done"}}],
                "usage": None,
            },
        ]
    )
    gw = openrouter_adapter.OpenRouterChatGateway(profile, client=fake, sleep=lambda _s: None)
    reply1 = gw.complete([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert len(fake.chat_calls) == 2
    assert reply1["usage"] == {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125}
    turn = gw.parse_turn(reply1)
    assert turn.tool_calls[0].call_id == "tc_1"
    assert turn.tool_calls[0].arguments == {"a": 1}

    reply2 = gw.complete([{"role": "user", "content": "finish"}])
    assert "usage" not in reply2

    fake_auth = _FakeOpenRouterSdkClient(
        chat_responses=[_openrouter_error(401, f"invalid key {secret}")]
    )
    gw_auth = openrouter_adapter.OpenRouterChatGateway(
        profile, client=fake_auth, sleep=lambda _s: None
    )
    gw_auth._secret = secret
    with pytest.raises(BackendError) as err401:
        gw_auth.complete([{"role": "user", "content": "hi"}])
    assert err401.value.error_class == "http-401"
    assert secret not in str(err401.value)
    assert "[REDACTED]" in str(err401.value)
    assert len(fake_auth.chat_calls) == 1


def test_openrouter_classify_probe_error_and_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = _or_profile(retries=0)

    for status, body, for_comp, expected_kind in [
        (401, "unauthorized", False, "auth-error"),
        (400, "context_length exceeded", True, "token-limit"),
        (429, "quota", True, "token-limit"),
        (404, "missing model", False, "client-error"),
        (502, "bad gateway", False, "tunnel-dead"),
    ]:
        kind, _detail, _hint = openrouter_adapter.classify_probe_error(
            _openrouter_error(status, body), or_prof, "sk-or-test-key", for_completion=for_comp
        )
        assert kind == expected_kind

    for exc_obj, expected_cls in [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connection"),
        (httpx.ProtocolError("bad proto"), "transport"),
    ]:
        gw = openrouter_adapter.OpenRouterChatGateway(
            or_prof,
            client=_FakeOpenRouterSdkClient(chat_responses=[exc_obj]),
            sleep=lambda _s: None,
        )
        with pytest.raises(BackendError) as err_chat:
            gw.complete([{"role": "user", "content": "hi"}])
        assert err_chat.value.error_class == expected_cls
