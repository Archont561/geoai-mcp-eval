"""Unit tests for ``experiment.adapters._sdk_probes``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import ollama as ollama_sdk
import pytest
from openrouter.errors import OpenRouterError

from experiment.adapters import _sdk_probes, backend_probe
from experiment.domain.backend import BackendProfile


def _openrouter_error(
    status: int, body: str, headers: dict[str, str] | None = None
) -> OpenRouterError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(status, text=body, headers=headers, request=req)
    return OpenRouterError(f"HTTP {status}: {body}", raw_response=resp, body=body)


class _FakeOllamaSdkClient:
    def __init__(
        self,
        *,
        chat_responses: list[Any] | None = None,
        list_responses: list[Any] | None = None,
    ) -> None:
        self._chat = list(chat_responses or [])
        self._list = list(list_responses or [])
        self.list_calls = 0

    def list(self) -> Any:
        self.list_calls += 1
        item = self._list.pop(0) if len(self._list) > 1 else self._list[0]
        if isinstance(item, Exception):
            raise item
        return item

    def chat(self, **kwargs: Any) -> Any:
        item = self._chat.pop(0) if len(self._chat) > 1 else self._chat[0]
        if isinstance(item, Exception):
            raise item
        return item


class _FakeOpenRouterSdkClient:
    def __init__(
        self,
        *,
        chat_responses: list[Any] | None = None,
        models_responses: list[Any] | None = None,
    ) -> None:
        self._chat_queue = list(chat_responses or [])
        self._models_queue = list(models_responses or [])
        self.exited = False
        self.chat = SimpleNamespace(send=self._send)
        self.models = SimpleNamespace(list=self._list)

    def _send(self, **_kwargs: Any) -> Any:
        item = self._chat_queue.pop(0) if len(self._chat_queue) > 1 else self._chat_queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def _list(self, **_kwargs: Any) -> Any:
        item = self._models_queue.pop(0) if len(self._models_queue) > 1 else self._models_queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def __exit__(self, *_exc: object) -> None:
        self.exited = True


def _or_profile(retries: int = 0) -> BackendProfile:
    return BackendProfile(
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen-2.5-coder-32b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
        retries=retries,
    )


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
    assert ok_client.list_calls == 3

    auth_client = _FakeOllamaSdkClient(
        list_responses=[ollama_sdk.ResponseError("denied", status_code=401)]
    )
    auth_probe = _sdk_probes.OllamaBackendProbe(profile, client=auth_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_auth:
        auth_probe.list_model_ids()
    assert e_auth.value.kind == "auth-error"
    assert auth_client.list_calls == 1

    tok_client = _FakeOllamaSdkClient(
        chat_responses=[ollama_sdk.ResponseError("context length exceeded", status_code=400)]
    )
    tok_probe = _sdk_probes.OllamaBackendProbe(profile, client=tok_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_tok:
        tok_probe.verify_tiny_completion(max_tokens=8)
    assert e_tok.value.kind == "token-limit"


def test_openrouter_and_ollama_probe_error_paths_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = _or_profile(retries=0)
    ollama_prof = BackendProfile(
        base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b", retries=0
    )

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

    owned_or = _FakeOpenRouterSdkClient()
    p_close = _sdk_probes.OpenRouterBackendProbe(or_prof, client=owned_or, sleep=lambda _s: None)
    p_close._owns_client = True
    p_close.close()
    assert owned_or.exited is True
