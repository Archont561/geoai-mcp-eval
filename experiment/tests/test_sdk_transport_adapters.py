"""Unit tests for GEO-022 SDK transport adapters (sshtunnel, ollama, openrouter)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import ollama as ollama_sdk
import paramiko
import pytest
import sshtunnel
from openrouter.errors import OpenRouterError

from experiment.adapters import _ollama_chat, _sdk_probes, backend_probe, harness_io, ollama
from experiment.adapters import openrouter as openrouter_adapter
from experiment.adapters.ssh_tunnel import (
    ManagedSshTunnel,
    SshTunnelAdapter,
    TunnelProbeError,
    TunnelSpec,
    parse_ssh_target,
)
from experiment.domain.backend import BackendError, BackendProfile
from experiment.services.backend_check import BackendCheckConfig, run_backend_check

# --- sshtunnel adapter ------------------------------------------------------


class _RecordingForwarder:
    def __init__(
        self,
        *,
        active: bool = True,
        port: int = 44556,
        start_exc: Exception | None = None,
    ) -> None:
        self.is_active = active
        self.local_bind_port = port
        self._start_exc = start_exc
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True
        if self._start_exc is not None:
            raise self._start_exc

    def stop(self) -> None:
        self.stopped = True
        self.is_active = False


def test_sshtunnel_target_parsing_and_managed_lifecycle() -> None:
    target = parse_ssh_target("alice@gpu.example.org:2222")
    assert (target.username, target.host, target.port) == ("alice", "gpu.example.org", 2222)
    simple = parse_ssh_target("gpu-box")
    assert (simple.username, simple.host, simple.port) == (None, "gpu-box", 22)
    with pytest.raises(TunnelProbeError) as empty_err:
        parse_ssh_target("   ")
    assert empty_err.value.kind == "ssh-unreachable"

    captured: dict[str, Any] = {}
    fwd = _RecordingForwarder(active=True, port=41234)

    def factory(**kwargs: Any) -> _RecordingForwarder:
        captured.update(kwargs)
        return fwd

    spec = TunnelSpec(ssh_host="alice@gpu.example.org:2222", ssh_password="pw")
    with ManagedSshTunnel(spec, forwarder_factory=factory) as tunnel:
        assert tunnel.is_active is True
        assert tunnel.local_bind_port == 41234
        assert captured["ssh_address_or_host"] == ("gpu.example.org", 2222)
        assert captured["ssh_username"] == "alice"
    assert fwd.started is True
    assert fwd.stopped is True
    assert tunnel.local_bind_port is None


def test_sshtunnel_error_classification_and_teardown() -> None:
    # Handler failure -> tunnel-dead
    with pytest.raises(TunnelProbeError) as handler_err:
        SshTunnelAdapter(
            forwarder_factory=lambda **_kw: _RecordingForwarder(
                start_exc=sshtunnel.HandlerSSHTunnelForwarderError("bind refused")
            )
        ).verify("gpu-box", None)
    assert handler_err.value.kind == "tunnel-dead"

    # Paramiko auth/SSH error -> ssh-unreachable
    with pytest.raises(TunnelProbeError) as auth_err:
        SshTunnelAdapter(
            forwarder_factory=lambda **_kw: _RecordingForwarder(
                start_exc=paramiko.SSHException("auth failed")
            )
        ).verify("gpu-box", None)
    assert auth_err.value.kind == "ssh-unreachable"

    # Inactive forwarder after start -> tunnel-dead + guaranteed stop()
    inactive = _RecordingForwarder(active=False)
    with pytest.raises(TunnelProbeError) as dead_err:
        SshTunnelAdapter(forwarder_factory=lambda **_kw: inactive).verify("gpu-box", None)
    assert dead_err.value.kind == "tunnel-dead"
    assert inactive.stopped is True


# --- ollama.Client SDK adapters --------------------------------------------


class _FakeOllamaSdkClient:
    def __init__(
        self,
        *,
        chat_responses: list[Any] | None = None,
        list_responses: list[Any] | None = None,
    ) -> None:
        self._chat = list(chat_responses or [])
        self._list = list(list_responses or [])
        self.chat_calls: list[dict[str, Any]] = []
        self.list_calls = 0

    def list(self) -> Any:
        self.list_calls += 1
        item = self._list.pop(0) if len(self._list) > 1 else self._list[0]
        if isinstance(item, Exception):
            raise item
        return item

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
    assert len(fake.chat_calls) == 2  # 503 retried once then succeeded
    assert fake.chat_calls[0]["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"x": 1}
    assert reply1["usage"] == {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
    gw = _ollama_chat.OllamaChatGateway(profile, client=fake)
    turn = gw.parse_turn(reply1)
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "filter_features"
    assert turn.tool_calls[0].arguments == {"iso": "POL"}

    # Missing counts stay absent (never imputed as 0)
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


def test_ollama_backend_probe_sdk_success_and_error_kinds() -> None:
    profile = BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b", retries=1)
    ok_client = _FakeOllamaSdkClient(
        list_responses=[
            ollama_sdk.ResponseError("transient", status_code=503),
            {"models": [{"model": "qwen2.5:3b", "digest": "sha256:aaa111"}]},
        ],
        chat_responses=[{"message": {"role": "assistant", "content": "OK"}}],
    )
    probe = _sdk_probes.OllamaBackendProbe(profile, client=ok_client, sleep=lambda _s: None)
    assert probe.list_model_ids() == {"qwen2.5:3b"}
    assert probe.resolve_model_digest() == "sha256:aaa111"
    probe.verify_tiny_completion(max_tokens=8)
    assert ok_client.list_calls == 3  # 503 + ok + digest

    # 401 never retried
    auth_client = _FakeOllamaSdkClient(
        list_responses=[ollama_sdk.ResponseError("denied", status_code=401)]
    )
    auth_probe = _sdk_probes.OllamaBackendProbe(profile, client=auth_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_auth:
        auth_probe.list_model_ids()
    assert e_auth.value.kind == "auth-error"
    assert auth_client.list_calls == 1

    # Token limit on chat
    tok_client = _FakeOllamaSdkClient(
        chat_responses=[ollama_sdk.ResponseError("context length exceeded", status_code=400)]
    )
    tok_probe = _sdk_probes.OllamaBackendProbe(profile, client=tok_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_tok:
        tok_probe.verify_tiny_completion(max_tokens=8)
    assert e_tok.value.kind == "token-limit"


# --- openrouter.OpenRouter SDK adapters ------------------------------------


def _openrouter_error(
    status: int, body: str, headers: dict[str, str] | None = None
) -> OpenRouterError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(status, text=body, headers=headers, request=req)
    return OpenRouterError(f"HTTP {status}: {body}", raw_response=resp, body=body)


class _FakeOpenRouterSdkClient:
    def __init__(
        self,
        *,
        chat_responses: list[Any] | None = None,
        models_responses: list[Any] | None = None,
    ) -> None:
        self._chat_queue = list(chat_responses or [])
        self._models_queue = list(models_responses or [])
        self.chat_calls: list[dict[str, Any]] = []
        self.models_calls = 0
        self.exited = False
        self.chat = SimpleNamespace(send=self._send)
        self.models = SimpleNamespace(list=self._list)

    def _send(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        item = self._chat_queue.pop(0) if len(self._chat_queue) > 1 else self._chat_queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def _list(self, **_kwargs: Any) -> Any:
        self.models_calls += 1
        item = self._models_queue.pop(0) if len(self._models_queue) > 1 else self._models_queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def __exit__(self, *_exc: object) -> None:
        self.exited = True


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

    # Missing usage stays absent (nullable, never imputed)
    reply2 = gw.complete([{"role": "user", "content": "finish"}])
    assert "usage" not in reply2

    # 401 never retried & redacts secret if echoed
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


def test_openrouter_probe_and_provider_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = _or_profile(retries=1)
    ollama_prof = BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b")
    custom_prof = BackendProfile(
        base_url="https://api.example.invalid/v1", model="custom", api_key_env="OPENROUTER_API_KEY"
    )

    assert isinstance(
        harness_io.create_chat_gateway(or_prof), openrouter_adapter.OpenRouterChatGateway
    )
    assert isinstance(harness_io.create_chat_gateway(ollama_prof), _ollama_chat.OllamaChatGateway)
    assert isinstance(harness_io.create_chat_gateway(custom_prof), harness_io.HttpChatGateway)

    assert isinstance(
        backend_probe.create_backend_probe(or_prof), _sdk_probes.OpenRouterBackendProbe
    )
    assert isinstance(
        backend_probe.create_backend_probe(ollama_prof), _sdk_probes.OllamaBackendProbe
    )
    assert isinstance(
        backend_probe.create_backend_probe(custom_prof), backend_probe.HttpBackendProbe
    )

    # Full run_backend_check on free-open without needing an SSH tunnel
    fake_or = _FakeOpenRouterSdkClient(
        models_responses=[{"result": {"data": [{"id": or_prof.model}]}}],
        chat_responses=[{"choices": [{"message": {"role": "assistant", "content": "OK"}}]}],
    )
    probe = _sdk_probes.OpenRouterBackendProbe(or_prof, client=fake_or, sleep=lambda _s: None)
    cfg = BackendCheckConfig(backend="free-open", poll_timeout_s=0.05, poll_interval_s=0.0)
    result = run_backend_check(cfg, backend_probe=probe, sleep=lambda _s: None)
    assert result.status == "READY"
    assert result.digest == or_prof.model
    assert ollama.is_ollama_profile(or_prof) is False
    assert ollama.is_ollama_profile(ollama_prof) is True


def test_openrouter_and_ollama_probe_error_paths_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = _or_profile(retries=0)
    ollama_prof = BackendProfile(
        base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b", retries=0
    )

    # OpenRouter classify_probe_error across auth, token-limit, 429, 4xx, 5xx
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

    # OpenRouter probe errors on list_model_ids, verify_tiny_completion, and transport
    for err, expected_kind in [
        (_openrouter_error(403, "forbidden"), "auth-error"),
        (httpx.ConnectError("offline"), "tunnel-dead"),
    ]:
        p = _sdk_probes.OpenRouterBackendProbe(
            or_prof, client=_FakeOpenRouterSdkClient(models_responses=[err]), sleep=lambda _s: None
        )
        with pytest.raises(backend_probe.BackendProbeError) as exc_info:
            p.list_model_ids()
        assert exc_info.value.kind == expected_kind

    empty_or = _sdk_probes.OpenRouterBackendProbe(
        or_prof,
        client=_FakeOpenRouterSdkClient(chat_responses=[{"choices": []}]),
        sleep=lambda _s: None,
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_empty:
        empty_or.verify_tiny_completion(max_tokens=8)
    assert e_empty.value.kind == "completion-rejected"

    # OpenRouter timeout & connection error translation on chat gateway
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

    # Ollama probe transport & empty completion errors
    conn_ol = _sdk_probes.OllamaBackendProbe(
        ollama_prof,
        client=_FakeOllamaSdkClient(list_responses=[httpx.ConnectError("down")]),
        sleep=lambda _s: None,
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_ol_conn:
        conn_ol.list_model_ids()
    assert e_ol_conn.value.kind == "tunnel-dead"

    empty_ol = _sdk_probes.OllamaBackendProbe(
        ollama_prof,
        client=_FakeOllamaSdkClient(chat_responses=[{"message": {}}]),
        sleep=lambda _s: None,
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_ol_empty:
        empty_ol.verify_tiny_completion(max_tokens=8)
    assert e_ol_empty.value.kind == "completion-rejected"

    # Gateway & probe close paths
    owned_or = _FakeOpenRouterSdkClient()
    p_close = _sdk_probes.OpenRouterBackendProbe(or_prof, client=owned_or, sleep=lambda _s: None)
    p_close._owns_client = True
    p_close.close()
    assert owned_or.exited is True
