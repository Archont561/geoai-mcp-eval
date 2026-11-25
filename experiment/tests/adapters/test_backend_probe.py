"""Unit tests for ``experiment.adapters.backend_probe``."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from experiment.adapters import _sdk_probes, backend_probe
from experiment.domain.backend import BackendProfile


def test_create_backend_probe_dispatches_by_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = BackendProfile(
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen-2.5-coder-32b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
    )
    ollama_prof = BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b")
    custom_prof = BackendProfile(
        base_url="https://api.example.invalid/v1", model="custom", api_key_env="OPENROUTER_API_KEY"
    )

    assert isinstance(
        backend_probe.create_backend_probe(or_prof), _sdk_probes.OpenRouterBackendProbe
    )
    assert isinstance(
        backend_probe.create_backend_probe(ollama_prof), _sdk_probes.OllamaBackendProbe
    )
    assert isinstance(
        backend_probe.create_backend_probe(custom_prof), backend_probe.HttpBackendProbe
    )


def test_http_backend_probe_end_to_end_with_respx(
    respx_mock: respx.MockRouter,
    backend_profile_factory: Any,
) -> None:
    profile = backend_profile_factory.build(
        base_url="https://api.example.invalid/v1",
        model="qwen2.5:3b",
    )
    respx_mock.get("https://api.example.invalid/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen2.5:3b"}]})
    )
    respx_mock.get("https://api.example.invalid/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "qwen2.5:3b", "digest": "sha256:probe99"}]}
        )
    )
    respx_mock.post("https://api.example.invalid/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "PONG"}}]},
        )
    )
    with httpx.Client() as client:
        probe = backend_probe.HttpBackendProbe(profile, session=client, sleep=lambda _: None)
        assert "qwen2.5:3b" in probe.list_model_ids()
        assert probe.resolve_model_digest() == "sha256:probe99"
        probe.verify_tiny_completion(max_tokens=8)
