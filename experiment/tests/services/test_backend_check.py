"""Unit tests for ``experiment.services.backend_check``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import sshtunnel
from fakes import make_mock_response
from hypothesis import given
from hypothesis import strategies as st
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
    BackendProbe,
    TunnelProbe,
    run_backend_check,
)


@pytest.fixture
def ok_http_session(fake_http_session: MagicMock) -> MagicMock:
    """``fake_http_session`` pre-configured with healthy ``/v1/models``, ``/api/tags``, and chat."""
    models_resp = make_mock_response(200, {"data": [{"id": "qwen2.5:3b"}]})
    tags_resp = make_mock_response(
        200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]}
    )
    chat_resp = make_mock_response(
        200,
        {"choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]},
    )

    def _get(url: str, **_kwargs: Any) -> MagicMock:
        if url.endswith("/v1/models"):
            return models_resp
        if url.endswith("/api/tags"):
            return tags_resp
        raise AssertionError(f"unexpected GET {url}")

    fake_http_session.get.side_effect = _get
    fake_http_session.post.return_value = chat_resp
    return fake_http_session


@pytest.fixture
def http_backend_probe(
    backend_check_config: BackendCheckConfig, ok_http_session: MagicMock
) -> HttpBackendProbe:
    profile = backends.resolve_profile(
        backend_check_config.backend,
        host=backend_check_config.host,
        model=backend_check_config.model,
    )
    return HttpBackendProbe(profile, session=ok_http_session, sleep=lambda _s: None)


def test_ready_exits_with_pinned_digest_only_after_tiny_completion(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> None:
    result = run_backend_check(
        backend_check_config,
        tunnel_probe=fake_ssh_tunnel_adapter,
        backend_probe=http_backend_probe,
        sleep=lambda _s: None,
    )
    assert result.status == "READY"
    assert result.model == "qwen2.5:3b"
    assert result.digest == "sha256:pinned123"
    assert BackendCheckResult.model_validate_json(result.model_dump_json()) == result
    assert ok_http_session.post.call_count == 1


def test_ssh_unreachable_produces_distinct_error(
    backend_check_config: BackendCheckConfig,
    fake_ssh_forwarder: MagicMock,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
) -> None:
    fake_ssh_forwarder.start.side_effect = sshtunnel.BaseSSHTunnelForwarderError(
        "Could not resolve hostname"
    )
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "ssh-unreachable"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_SSH_UNREACHABLE
    assert "gpu-box" in str(exc_info.value)


def test_dead_controlmaster_tunnel_produces_distinct_error(
    backend_check_config: BackendCheckConfig,
    fake_ssh_forwarder: MagicMock,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
) -> None:
    fake_ssh_forwarder.is_active = False
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "tunnel-dead"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_TUNNEL_DEAD


def test_missing_control_socket_reports_tunnel_dead(
    tmp_path: Path,
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
) -> None:
    cfg = backend_check_config.model_copy(update={"control_path": tmp_path / "does-not-exist.sock"})
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(cfg, tunnel_probe=fake_ssh_tunnel_adapter, sleep=lambda _s: None)
    assert exc_info.value.kind == "tunnel-dead"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_TUNNEL_DEAD


def test_absent_model_or_digest_mismatch_fails_distinctly(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> None:
    cfg = backend_check_config.model_copy(update={"poll_timeout_s": 0.01})
    other_models = make_mock_response(200, {"data": [{"id": "other:1b"}]})
    other_tags = make_mock_response(
        200, {"models": [{"name": "other:1b", "digest": "sha256:other"}]}
    )
    ok_http_session.get.side_effect = lambda url, **_kw: (
        other_models if url.endswith("/v1/models") else other_tags
    )

    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            cfg,
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "model-absent"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_MODEL_ABSENT
    ok_http_session.post.assert_not_called()


def test_no_silent_retry_on_auth_or_4xx(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> None:
    ok_http_session.get.side_effect = None
    ok_http_session.get.return_value = make_mock_response(401, text="invalid api key")
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "auth-error"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_AUTH_CLIENT
    assert ok_http_session.get.call_count == 1


def test_retries_only_on_429_or_5xx_then_succeeds(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> None:
    models_queue = [
        make_mock_response(503, text="overloaded"),
        make_mock_response(200, {"data": [{"id": "qwen2.5:3b"}]}),
    ]
    tags_resp = make_mock_response(
        200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]}
    )
    ok_http_session.get.side_effect = lambda url, **_kw: (
        models_queue.pop(0) if url.endswith("/v1/models") else tags_resp
    )
    ok_http_session.post.side_effect = [
        make_mock_response(429, text="slow down"),
        make_mock_response(
            200,
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                ]
            },
        ),
    ]
    result = run_backend_check(
        backend_check_config,
        tunnel_probe=fake_ssh_tunnel_adapter,
        backend_probe=http_backend_probe,
        sleep=lambda _s: None,
    )
    assert result.status == "READY"
    assert ok_http_session.post.call_count == 2


def test_token_limit_rejection_is_distinct_and_not_retried_on_400(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> None:
    ok_http_session.post.return_value = make_mock_response(
        400, text="maximum context length / token limit exceeded"
    )
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "token-limit"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_TOKEN_LIMIT
    assert ok_http_session.post.call_count == 1


def test_completion_rejected_on_empty_choices(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> None:
    ok_http_session.post.return_value = make_mock_response(200, {"choices": []})
    with pytest.raises(BackendCheckError) as exc_info:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    assert exc_info.value.kind == "completion-rejected"
    assert backend_check_exit_code(exc_info.value.kind) == EXIT_COMPLETION_REJECTED


def test_backend_check_pure_ports_without_http_or_subprocess(
    backend_check_config: BackendCheckConfig,
) -> None:
    tunnel = MagicMock(spec=TunnelProbe)
    probe = MagicMock(spec=BackendProbe)
    probe.list_model_ids.return_value = {"qwen2.5:3b"}
    probe.resolve_model_digest.return_value = "sha256:pinned123"

    result = run_backend_check(
        backend_check_config, tunnel_probe=tunnel, backend_probe=probe, sleep=lambda _s: None
    )
    assert result.status == "READY"
    tunnel.verify.assert_called_once_with("gpu-box", backend_check_config.control_path)
    probe.verify_tiny_completion.assert_called_once_with(max_tokens=backend_check_config.max_tokens)
    probe.close.assert_not_called()


def test_backend_check_edge_errors_and_openrouter_ready(
    monkeypatch: pytest.MonkeyPatch,
    backend_check_config: BackendCheckConfig,
    openrouter_profile: BackendProfile,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
    fake_openrouter_sdk_client: MagicMock,
) -> None:
    with pytest.raises(BackendCheckError) as e1:
        run_backend_check(
            backend_check_config.model_copy(update={"ssh_host": None}),
            tunnel_probe=fake_ssh_tunnel_adapter,
            sleep=lambda _s: None,
        )
    assert backend_check_exit_code(e1.value.kind) == EXIT_SSH_UNREACHABLE

    with pytest.raises(BackendCheckError) as e2:
        run_backend_check(
            backend_check_config.model_copy(update={"backend": "no-such-backend"}),
            tunnel_probe=fake_ssh_tunnel_adapter,
        )
    assert backend_check_exit_code(e2.value.kind) == EXIT_AUTH_CLIENT

    ok_http_session.get.side_effect = httpx.ConnectError("refused")
    with pytest.raises(BackendCheckError) as e3:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    assert backend_check_exit_code(e3.value.kind) == EXIT_TUNNEL_DEAD

    models_resp = make_mock_response(200, {"data": [{"id": "qwen2.5:3b"}]})
    tags_resp = make_mock_response(
        200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]}
    )
    ok_http_session.get.side_effect = lambda url, **_kw: (
        models_resp if url.endswith("/v1/models") else tags_resp
    )

    for status_code, text, expected_exit, expected_posts in [
        (429, "quota", EXIT_TOKEN_LIMIT, 4),
        (401, "denied", EXIT_AUTH_CLIENT, 1),
        (500, "crash", EXIT_COMPLETION_REJECTED, 4),
    ]:
        ok_http_session.post.reset_mock()
        ok_http_session.post.return_value = make_mock_response(status_code, text=text)
        with pytest.raises(BackendCheckError) as err:
            run_backend_check(
                backend_check_config,
                tunnel_probe=fake_ssh_tunnel_adapter,
                backend_probe=http_backend_probe,
                sleep=lambda _s: None,
            )
        assert backend_check_exit_code(err.value.kind) == expected_exit
        assert ok_http_session.post.call_count == expected_posts

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    or_prof = openrouter_profile.model_copy(update={"retries": 0})
    fake_openrouter_sdk_client.models.list.return_value = {
        "result": {"data": [{"id": or_prof.model}]}
    }
    or_probe = _sdk_probes.OpenRouterBackendProbe(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    or_res = run_backend_check(
        BackendCheckConfig(backend="free-open", poll_timeout_s=0.05, poll_interval_s=0.0),
        backend_probe=or_probe,
        sleep=lambda _s: None,
    )
    assert or_res.status == "READY"
    assert or_res.digest == or_prof.model


@given(max_tokens=st.integers(max_value=0))
def test_backend_check_config_rejects_non_positive_max_tokens(max_tokens: int) -> None:
    with pytest.raises(ValidationError):
        BackendCheckConfig(max_tokens=max_tokens)
