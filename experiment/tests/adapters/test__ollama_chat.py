"""Unit tests for ``experiment.adapters._ollama_chat``."""

from __future__ import annotations

import json
from typing import Any

import httpx
import ollama as ollama_sdk
import pytest

from experiment.adapters import _ollama_chat
from experiment.domain.backend import BackendError, BackendProfile


class _FakeOllamaSdkClient:
    def __init__(self, *, chat_responses: list[Any] | None = None) -> None:
        self._chat = list(chat_responses or [])
        self.chat_calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        item = self._chat.pop(0) if len(self._chat) > 1 else self._chat[0]
        if isinstance(item, Exception):
            raise item
        return item


def test_ollama_chat_gateway_tool_calls_usage_and_retries() -> None:
    profile = BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b", retries=2)
    fake = _FakeOllamaSdkClient(
        chat_responses=[
            ollama_sdk.ResponseError("busy", status_code=503),
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "filter_features", "arguments": {"iso": "POL"}}}
                    ],
                },
                "prompt_eval_count": 40,
                "eval_count": 12,
                "done_reason": "stop",
            },
            {
                "message": {"role": "assistant", "content": "final answer"},
                "done_reason": "stop",
            },
        ]
    )

    reply1 = _ollama_chat.chat_completions_sdk(
        profile,
        [
            {"role": "user", "content": "check POL"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "prev_tool", "arguments": json.dumps({"x": 1})}}
                ],
            },
        ],
        tools=[{"type": "function", "function": {"name": "filter_features"}}],
        client=fake,
        sleep=lambda _s: None,
    )
    assert len(fake.chat_calls) == 2
    assert fake.chat_calls[0]["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"x": 1}
    assert reply1["usage"] == {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
    gw = _ollama_chat.OllamaChatGateway(profile, client=fake)
    turn = gw.parse_turn(reply1)
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "filter_features"
    assert turn.tool_calls[0].arguments == {"iso": "POL"}

    reply2 = gw.complete([{"role": "user", "content": "done"}])
    assert "usage" not in reply2
    assert reply2["choices"][0]["message"]["content"] == "final answer"


def test_ollama_chat_no_retry_on_4xx_and_transport_errors() -> None:
    profile = BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b", retries=3)
    fake_400 = _FakeOllamaSdkClient(
        chat_responses=[ollama_sdk.ResponseError("bad request", status_code=400)]
    )
    with pytest.raises(BackendError) as err400:
        _ollama_chat.chat_completions_sdk(
            profile, [{"role": "user", "content": "hi"}], client=fake_400, sleep=lambda _s: None
        )
    assert err400.value.error_class == "http-400"
    assert len(fake_400.chat_calls) == 1

    fake_timeout = _FakeOllamaSdkClient(chat_responses=[httpx.ReadTimeout("slow")])
    with pytest.raises(BackendError) as err_to:
        _ollama_chat.chat_completions_sdk(
            profile, [{"role": "user", "content": "hi"}], client=fake_timeout, sleep=lambda _s: None
        )
    assert err_to.value.error_class == "timeout"
