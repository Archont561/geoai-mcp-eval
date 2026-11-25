"""Unit tests for ``experiment.adapters._ollama_chat``."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import ollama as ollama_sdk
import pytest

from experiment.adapters import _ollama_chat
from experiment.domain.backend import BackendError, BackendProfile


def test_ollama_chat_gateway_tool_calls_usage_and_retries(
    ollama_profile: BackendProfile,
    fake_ollama_sdk_client: MagicMock,
) -> None:
    fake_ollama_sdk_client.chat.side_effect = [
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

    reply1 = _ollama_chat.chat_completions_sdk(
        ollama_profile,
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
        client=fake_ollama_sdk_client,
        sleep=lambda _s: None,
    )
    assert fake_ollama_sdk_client.chat.call_count == 2
    first_kwargs = fake_ollama_sdk_client.chat.call_args_list[0].kwargs
    assert first_kwargs["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"x": 1}
    assert reply1["usage"] == {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}

    gw = _ollama_chat.OllamaChatGateway(ollama_profile, client=fake_ollama_sdk_client)
    turn = gw.parse_turn(reply1)
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "filter_features"
    assert turn.tool_calls[0].arguments == {"iso": "POL"}

    reply2 = gw.complete([{"role": "user", "content": "done"}])
    assert "usage" not in reply2
    assert reply2["choices"][0]["message"]["content"] == "final answer"


def test_ollama_chat_no_retry_on_4xx_and_transport_errors(
    ollama_profile: BackendProfile,
    fake_ollama_sdk_client: MagicMock,
) -> None:
    profile = ollama_profile.model_copy(update={"retries": 3})
    fake_ollama_sdk_client.chat.side_effect = ollama_sdk.ResponseError(
        "bad request", status_code=400
    )
    with pytest.raises(BackendError) as err400:
        _ollama_chat.chat_completions_sdk(
            profile,
            [{"role": "user", "content": "hi"}],
            client=fake_ollama_sdk_client,
            sleep=lambda _s: None,
        )
    assert err400.value.error_class == "http-400"
    assert fake_ollama_sdk_client.chat.call_count == 1

    fake_ollama_sdk_client.chat.reset_mock()
    fake_ollama_sdk_client.chat.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(BackendError) as err_to:
        _ollama_chat.chat_completions_sdk(
            profile,
            [{"role": "user", "content": "hi"}],
            client=fake_ollama_sdk_client,
            sleep=lambda _s: None,
        )
    assert err_to.value.error_class == "timeout"
