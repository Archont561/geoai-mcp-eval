"""Unit tests for ``experiment.adapters.backend_probe``."""

from __future__ import annotations

import pytest

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
