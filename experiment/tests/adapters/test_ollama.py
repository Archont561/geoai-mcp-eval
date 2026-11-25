"""Unit tests for ``experiment.adapters.ollama``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import ValidationError

from experiment.adapters import ollama
from experiment.domain.backend import BackendProfile


def test_ollama_adapter_no_longer_exposes_create_session() -> None:
    assert not hasattr(ollama, "create_session")


def test_ollama_adapter_probes_retries_and_daemon_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ollama as ollama_sdk

    class _FakeOllamaClient:
        def __init__(self, *, fail_list: bool = False, fail_pull: bool = False) -> None:
            self.fail_list = fail_list
            self.fail_pull = fail_pull

        def list(self) -> dict[str, Any]:
            if self.fail_list:
                raise ollama_sdk.RequestError("down")
            return {"models": [{"model": "qwen2.5:3b", "digest": "sha256:sdk123"}]}

        def pull(self, _model: str, *, stream: bool = False) -> dict[str, Any]:
            if self.fail_pull:
                raise ollama_sdk.ResponseError("pull failed", status_code=500)
            return {"status": "success"}

        def generate(self, **_kw: Any) -> dict[str, Any]:
            return {"response": "OK"}

    monkeypatch.setattr(ollama, "build_client", lambda *_a, **_kw: _FakeOllamaClient())
    assert ollama.serve_running() is True
    assert ollama.wait_ready(attempts=1, sleep_s=0) is True
    assert ollama.start_ollama("/usr/bin/ollama", tmp_path / "serve.log") is None
    assert ollama.pull_model("/usr/bin/ollama", "qwen2.5:3b") == 0
    assert ollama.smoke_generate("qwen2.5:3b") == {"response": "OK"}
    assert ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b") == "sha256:sdk123"

    monkeypatch.setattr(
        ollama, "build_client", lambda *_a, **_kw: _FakeOllamaClient(fail_list=True, fail_pull=True)
    )
    assert ollama.serve_running() is False
    assert ollama.wait_ready(attempts=2, sleep_s=0, sleep=lambda _s: None) is False
    assert ollama.pull_model("/usr/bin/ollama", "qwen2.5:3b") == 1
    assert ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b") == "unavailable"

    events: list[str] = []

    class FakeProc:
        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> int:
            events.append(f"wait:{timeout}")
            raise subprocess.TimeoutExpired(cmd="ollama", timeout=timeout or 0)

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(ollama.subprocess, "Popen", lambda *_a, **_kw: FakeProc())
    owner = ollama.start_ollama("/usr/bin/ollama", tmp_path / "logs" / "ollama.log")
    assert owner is not None
    ollama.stop_ollama(owner)
    assert events == ["terminate", "wait:10", "kill"]
    assert owner.log_handle.closed is True

    def broken_call(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.ConnectionError("refused")

    with pytest.raises(ollama.HttpTransportError):
        ollama.request_with_retry(
            broken_call,
            "http://127.0.0.1:11434/v1/models",
            ollama.RetryPolicy(timeout=(1.0, 2.0), retries=0),
        )


def test_retry_policy_and_is_ollama_profile() -> None:
    policy = ollama.RetryPolicy(timeout=(1.0, 5.0), retries=2)
    assert ollama.RetryPolicy.model_validate_json(policy.model_dump_json()) == policy
    with pytest.raises(ValidationError):
        ollama.RetryPolicy(retries=-1)

    or_prof = BackendProfile(
        base_url="https://openrouter.ai/api/v1", model="m", api_key_env="OPENROUTER_API_KEY"
    )
    ollama_prof = BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b")
    assert ollama.is_ollama_profile(or_prof) is False
    assert ollama.is_ollama_profile(ollama_prof) is True
