"""Unit tests for ``experiment.services.backend_check``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
import sshtunnel
from pydantic import ValidationError

from experiment.adapters import _sdk_probes, backends
from experiment.adapters.backend_probe import HttpBackendProbe
from experiment.adapters.ssh_tunnel import SshTunnelAdapter
from experiment.cli.env import (
    EXIT_AUTH_CLIENT,
    EXIT_COMPLETION_REJECTED,
    EXIT_MODEL_ABSENT,
    EXIT_SSH_UNREACHABLE,
    EXIT_TOKEN_LIMIT,
    EXIT_TUNNEL_DEAD,
    backend_check_exit_code,
)
from experiment.domain.backend import BackendProfile
from experiment.services.backend_check import (
    BackendCheckConfig,
    BackendCheckError,
    BackendCheckResult,
    run_backend_check,
)


class _StubResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or ("" if payload is None else str(payload))
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _StubSession:
    def __init__(
        self,
        get_map: dict[str, list[_StubResponse | Exception]],
        post_list: list[_StubResponse | Exception] | None = None,
    ) -> None:
        self._get_map = {k: list(v) for k, v in get_map.items()}
        self._post_list = list(post_list or [])
        self.get_calls: list[str] = []
        self.post_calls: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> _StubResponse:
        self.get_calls.append(url)
        for suffix, queue in self._get_map.items():
            if url.endswith(suffix):
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, **_kwargs: Any) -> _StubResponse:
        self.post_calls.append(url)
        item = self._post_list.pop(0) if len(self._post_list) > 1 else self._post_list[0]
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        return None


class _FakeForwarder:
    def __init__(self, *, active: bool = True, start_exc: Exception | None = None) -> None:
        self.is_active = active
        self.local_bind_port = 54321
        self._start_exc = start_exc
        self.stopped = False

    def start(self) -> None:
        if self._start_exc is not None:
            raise self._start_exc

    def stop(self) -> None:
        self.stopped = True


def _cfg(tmp_path: Path, **overrides: Any) -> BackendCheckConfig:
    sock = tmp_path / "ollama.sock"
    sock.write_text("", encoding="utf-8")
    defaults: dict[str, Any] = {
        "backend": "remote-ollama",
        "model": "qwen2.5:3b",
        "ssh_host": "gpu-box",
        "control_path": sock,
        "expected_digest": "sha256:pinned123",
        "poll_timeout_s": 0.05,
        "poll_interval_s": 0.0,
    }
    defaults.update(overrides)
    return BackendCheckConfig(**defaults)


def _http_probe(cfg: BackendCheckConfig, session: _StubSession) -> HttpBackendProbe:
    profile = backends.resolve_profile(cfg.backend, host=cfg.host, model=cfg.model)
    return HttpBackendProbe(profile, session=session, sleep=lambda _s: None)


def _ok_tunnel() -> SshTunnelAdapter:
    return SshTunnelAdapter(forwarder_factory=lambda **_kw: _FakeForwarder(active=True))


def test_ready_exits_with_pinned_digest_only_after_tiny_completion(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    session = _StubSession(
        get_map={
            "/v1/models": [_StubResponse(200, {"data": [{"id": "qwen2.5:3b"}]})],
            "/api/tags": [
                _StubResponse(
                    200,
                    {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]},
                )
            ],
        },
        post_list=[
            _StubResponse(
                200,
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                    ]
                },
            )
        ],
    )
    result = run_backend_check(
        cfg,
        tunnel_probe=_ok_tunnel(),
        backend_probe=_http_probe(cfg, session),
        sleep=lambda _s: None,
    )
    assert result.status == "READY"
    assert result.model == "qwen2.5:3b"
    assert result.digest == "sha256:pinned123"
    assert BackendCheckResult.model_validate_json(result.model_dump_json()) == result
    assert len(session.post_calls) == 1


def test_ssh_unreachable_produces_distinct_error(tmp_path: Path) -> None:
    def fail_ssh(**_kw: Any) -> _FakeForwarder:
        return _FakeForwarder(
            start_exc=sshtunnel.BaseSSHTunnelForwarderError("Could not resolve hostname")
        )

    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            _cfg(tmp_path),
            tunnel_probe=SshTunnelAdapter(forwarder_factory=fail_ssh),
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "ssh-unreachable"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_SSH_UNREACHABLE
    assert "gpu-box" in str(exc_info.value)


def test_dead_controlmaster_tunnel_produces_distinct_error(tmp_path: Path) -> None:
    def dead_tunnel(**_kw: Any) -> _FakeForwarder:
        return _FakeForwarder(active=False)

    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            _cfg(tmp_path),
            tunnel_probe=SshTunnelAdapter(forwarder_factory=dead_tunnel),
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "tunnel-dead"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_TUNNEL_DEAD


def test_missing_control_socket_reports_tunnel_dead(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, control_path=tmp_path / "does-not-exist.sock")
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(cfg, tunnel_probe=_ok_tunnel(), sleep=lambda _s: None)
    assert exc_info.value.kind == "tunnel-dead"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_TUNNEL_DEAD


def test_absent_model_or_digest_mismatch_fails_distinctly(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, poll_timeout_s=0.01)
    session = _StubSession(
        get_map={
            "/v1/models": [_StubResponse(200, {"data": [{"id": "other:1b"}]})],
            "/api/tags": [
                _StubResponse(200, {"models": [{"name": "other:1b", "digest": "sha256:other"}]})
            ],
        },
        post_list=[],
    )
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, session),
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "model-absent"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_MODEL_ABSENT
    assert session.post_calls == []


def test_no_silent_retry_on_auth_or_4xx(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    session = _StubSession(
        get_map={"/v1/models": [_StubResponse(401, text="invalid api key")]},
    )
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, session),
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "auth-error"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_AUTH_CLIENT
    assert len(session.get_calls) == 1


def test_retries_only_on_429_or_5xx_then_succeeds(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    session = _StubSession(
        get_map={
            "/v1/models": [
                _StubResponse(503, text="overloaded"),
                _StubResponse(200, {"data": [{"id": "qwen2.5:3b"}]}),
            ],
            "/api/tags": [
                _StubResponse(
                    200,
                    {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]},
                )
            ],
        },
        post_list=[
            _StubResponse(429, text="slow down"),
            _StubResponse(
                200,
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                    ]
                },
            ),
        ],
    )
    result = run_backend_check(
        cfg,
        tunnel_probe=_ok_tunnel(),
        backend_probe=_http_probe(cfg, session),
        sleep=lambda _s: None,
    )
    assert result.status == "READY"
    assert len(session.post_calls) == 2


def test_token_limit_rejection_is_distinct_and_not_retried_on_400(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    session = _StubSession(
        get_map={
            "/v1/models": [_StubResponse(200, {"data": [{"id": "qwen2.5:3b"}]})],
            "/api/tags": [
                _StubResponse(
                    200,
                    {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]},
                )
            ],
        },
        post_list=[
            _StubResponse(400, text="maximum context length / token limit exceeded"),
        ],
    )
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, session),
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "token-limit"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_TOKEN_LIMIT
    assert len(session.post_calls) == 1


def test_completion_rejected_on_empty_choices(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    session = _StubSession(
        get_map={
            "/v1/models": [_StubResponse(200, {"data": [{"id": "qwen2.5:3b"}]})],
            "/api/tags": [
                _StubResponse(
                    200,
                    {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]},
                )
            ],
        },
        post_list=[_StubResponse(200, {"choices": []})],
    )
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, session),
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "completion-rejected"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_COMPLETION_REJECTED


def test_backend_check_pure_ports_without_http_or_subprocess(tmp_path: Path) -> None:
    class _FakeTunnel:
        def __init__(self) -> None:
            self.calls: list[tuple[str | None, Path | None]] = []

        def verify(self, ssh_host: str | None, control_path: Path | None) -> None:
            self.calls.append((ssh_host, control_path))

    class _FakeProbe:
        def __init__(self) -> None:
            self.max_tokens_seen: int | None = None
            self.closed = False

        def list_model_ids(self) -> set[str]:
            return {"qwen2.5:3b"}

        def resolve_model_digest(self) -> str | None:
            return "sha256:pinned123"

        def verify_tiny_completion(self, *, max_tokens: int) -> None:
            self.max_tokens_seen = max_tokens

        def close(self) -> None:
            self.closed = True

    tunnel = _FakeTunnel()
    probe = _FakeProbe()
    cfg = _cfg(tmp_path)
    result = run_backend_check(cfg, tunnel_probe=tunnel, backend_probe=probe, sleep=lambda _s: None)
    assert result.status == "READY"
    assert tunnel.calls == [("gpu-box", cfg.control_path)]
    assert probe.max_tokens_seen == cfg.max_tokens
    assert probe.closed is False


def test_backend_check_edge_errors_and_openrouter_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(BackendCheckError) as e1:
        run_backend_check(
            _cfg(tmp_path, ssh_host=None), tunnel_probe=_ok_tunnel(), sleep=lambda _s: None
        )
    assert backend_check_exit_code(e1.value.kind) == EXIT_SSH_UNREACHABLE

    with pytest.raises(BackendCheckError) as e2:
        run_backend_check(_cfg(tmp_path, backend="no-such-backend"), tunnel_probe=_ok_tunnel())
    assert backend_check_exit_code(e2.value.kind) == EXIT_AUTH_CLIENT

    cfg = _cfg(tmp_path)
    conn_session = _StubSession(
        get_map={"/v1/models": [requests.exceptions.ConnectionError("refused")]}
    )
    with pytest.raises(BackendCheckError) as e3:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, conn_session),
            sleep=lambda _s: None,
        )
    assert backend_check_exit_code(e3.value.kind) == EXIT_TUNNEL_DEAD

    ok_models = {
        "/v1/models": [_StubResponse(200, {"data": [{"id": "qwen2.5:3b"}]})],
        "/api/tags": [
            _StubResponse(200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]})
        ],
    }
    rl_session = _StubSession(get_map=ok_models, post_list=[_StubResponse(429, text="quota")])
    with pytest.raises(BackendCheckError) as e4:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, rl_session),
            sleep=lambda _s: None,
        )
    assert backend_check_exit_code(e4.value.kind) == EXIT_TOKEN_LIMIT
    assert len(rl_session.post_calls) == 4

    auth_session = _StubSession(get_map=ok_models, post_list=[_StubResponse(401, text="denied")])
    with pytest.raises(BackendCheckError) as e5:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, auth_session),
            sleep=lambda _s: None,
        )
    assert backend_check_exit_code(e5.value.kind) == EXIT_AUTH_CLIENT
    assert len(auth_session.post_calls) == 1

    err_session = _StubSession(get_map=ok_models, post_list=[_StubResponse(500, text="crash")])
    with pytest.raises(BackendCheckError) as e6:
        run_backend_check(
            cfg,
            tunnel_probe=_ok_tunnel(),
            backend_probe=_http_probe(cfg, err_session),
            sleep=lambda _s: None,
        )
    assert backend_check_exit_code(e6.value.kind) == EXIT_COMPLETION_REJECTED
    assert len(err_session.post_calls) == 4

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    or_prof = BackendProfile(
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen-2.5-coder-32b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
    )
    fake_or = SimpleNamespace(
        models=SimpleNamespace(list=lambda **_kw: {"result": {"data": [{"id": or_prof.model}]}}),
        chat=SimpleNamespace(
            send=lambda **_kw: {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        ),
    )
    or_probe = _sdk_probes.OpenRouterBackendProbe(or_prof, client=fake_or, sleep=lambda _s: None)
    or_res = run_backend_check(
        BackendCheckConfig(backend="free-open", poll_timeout_s=0.05, poll_interval_s=0.0),
        backend_probe=or_probe,
        sleep=lambda _s: None,
    )
    assert or_res.status == "READY"
    assert or_res.digest == or_prof.model

    with pytest.raises(ValidationError):
        BackendCheckConfig(max_tokens=0)
