"""Executable specifications for backend readiness checks."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import ollama as ollama_sdk
import pytest
import sshtunnel
from fakes import make_mock_response
from openrouter.errors import OpenRouterError
from pytest_bdd import given, parsers, scenarios, then, when

from experiment.adapters import _ollama_chat, _sdk_probes, backend_probe
from experiment.adapters import openrouter as openrouter_adapter
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
from experiment.domain.backend import BackendError, BackendProfile
from experiment.services.backend_check import (
    BackendCheckConfig,
    BackendCheckError,
    BackendCheckResult,
    run_backend_check,
)

ROOT = Path(__file__).resolve().parents[3]
scenarios(str(ROOT / "experiment" / "features" / "backend-preflight.feature"))


@pytest.fixture
def preflight(backend_check_config: BackendCheckConfig) -> dict:
    return {"config": backend_check_config}


def assert_failure(preflight: dict, kind: str, exit_code: int) -> BackendCheckError:
    error = preflight["error"]
    assert error.kind == kind
    assert backend_check_exit_code(error.kind) == exit_code
    return error


@pytest.fixture
def rate_limit_error():
    import httpx
    from openrouter.errors import OpenRouterError

    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(429, text="rate limited", headers={"Retry-After": "1"}, request=req)
    return OpenRouterError("HTTP 429: rate limited", raw_response=resp, body="rate limited")


@pytest.fixture
def forbidden_openrouter_error() -> OpenRouterError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(403, text="forbidden", request=req)
    return OpenRouterError("HTTP 403: forbidden", raw_response=resp, body="forbidden")


# Step definitions follow feature and scenario order; shared steps appear at first use.

# backend-preflight.feature — A reachable model responds successfully


@given("a working connection and the requested model")
def working_backend() -> None:
    """The shared fixtures provide a healthy tunnel and model endpoint."""


@when("the researcher checks backend readiness")
def check_backend(
    preflight: dict,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
) -> None:
    try:
        preflight["result"] = run_backend_check(
            preflight["config"],
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    except BackendCheckError as exc:
        preflight["error"] = exc


@then("the backend is ready with the model version pinned")
def ready_with_digest(preflight: dict) -> None:
    result = preflight["result"]
    assert result.status == "READY"
    assert result.model == "qwen2.5:3b"
    assert result.digest == "sha256:pinned123"
    assert BackendCheckResult.model_validate_json(result.model_dump_json()) == result


@then("one test response was requested")
def one_response(ok_http_session: MagicMock) -> None:
    assert ok_http_session.post.call_count == 1


# backend-preflight.feature — The remote host cannot be reached


@given("the remote host cannot be reached")
def unreachable_host(fake_ssh_forwarder: MagicMock) -> None:
    fake_ssh_forwarder.start.side_effect = sshtunnel.BaseSSHTunnelForwarderError(
        "Could not resolve hostname"
    )


@then("the report identifies an unreachable remote host")
def host_error(preflight: dict) -> None:
    error = assert_failure(preflight, "ssh-unreachable", EXIT_SSH_UNREACHABLE)
    assert "gpu-box" in str(error)


# backend-preflight.feature — The existing tunnel is inactive


@given("the connection tunnel is inactive")
def inactive_tunnel(fake_ssh_forwarder: MagicMock) -> None:
    fake_ssh_forwarder.is_active = False


@then("the report identifies an unavailable tunnel")
def tunnel_error(preflight: dict, fake_ssh_forwarder: MagicMock) -> None:
    assert_failure(preflight, "tunnel-dead", EXIT_TUNNEL_DEAD)
    if fake_ssh_forwarder.start.called and not fake_ssh_forwarder.is_active:
        fake_ssh_forwarder.stop.assert_called_once()


# backend-preflight.feature — The existing tunnel connection is missing


@given("the configured tunnel connection is missing")
def missing_tunnel(preflight: dict, tmp_path: Path) -> None:
    preflight["config"] = preflight["config"].model_copy(
        update={"control_path": tmp_path / "does-not-exist.sock"}
    )


# backend-preflight.feature — The requested model is absent


@given("the backend has only a different model")
def wrong_model(preflight: dict, ok_http_session: MagicMock) -> None:
    preflight["config"] = preflight["config"].model_copy(update={"poll_timeout_s": 0.01})
    models = make_mock_response(200, {"data": [{"id": "other:1b"}]})
    tags = make_mock_response(200, {"models": [{"name": "other:1b", "digest": "sha256:other"}]})
    ok_http_session.get.side_effect = lambda url, **_kw: (
        models if url.endswith("/v1/models") else tags
    )


@then("the report identifies the missing model")
def model_error(preflight: dict) -> None:
    assert_failure(preflight, "model-absent", EXIT_MODEL_ABSENT)


@then("no test response was requested")
def no_response(ok_http_session: MagicMock) -> None:
    ok_http_session.post.assert_not_called()


# backend-preflight.feature — The local model service responds to preparation and readiness checks


@given("a local model service with a prepared model", target_fixture="local_model_service")
def prepared_local_service(monkeypatch: pytest.MonkeyPatch) -> dict:
    from experiment.adapters import ollama

    client = MagicMock()
    client.list.return_value = {"models": [{"model": "qwen2.5:3b", "digest": "sha256:sdk123"}]}
    client.pull.return_value = {"status": "success"}
    client.generate.return_value = {"response": "OK"}
    monkeypatch.setattr(ollama, "build_client", lambda *_a, **_kw: client)
    return {"client": client}


@when("the researcher checks and prepares the local service")
def check_prepared_local_service(local_model_service: dict, tmp_path: Path) -> None:
    from experiment.adapters import ollama

    local_model_service["running"] = ollama.serve_running()
    local_model_service["ready"] = ollama.wait_ready(attempts=1, sleep_s=0)
    local_model_service["owner"] = ollama.start_ollama("/usr/bin/ollama", tmp_path / "serve.log")
    local_model_service["pull"] = ollama.pull_model("/usr/bin/ollama", "qwen2.5:3b")
    local_model_service["response"] = ollama.smoke_generate("qwen2.5:3b")
    local_model_service["digest"] = ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b")


@then("model readiness, identity, and a test response are available")
def prepared_local_service_responds(local_model_service: dict) -> None:
    assert local_model_service["running"] is True and local_model_service["ready"] is True
    assert local_model_service["owner"] is None and local_model_service["pull"] == 0
    assert local_model_service["response"] == {"response": "OK"}
    assert local_model_service["digest"] == "sha256:sdk123"


# backend-preflight.feature — An unavailable local service can be started and stopped safely


@given("a local model service that cannot be reached", target_fixture="unavailable_local_service")
def local_service_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> dict:
    import ollama as ollama_sdk

    from experiment.adapters import ollama

    client = MagicMock()
    client.list.side_effect = ollama_sdk.RequestError("down")
    client.pull.side_effect = ollama_sdk.ResponseError("pull failed", status_code=500)
    monkeypatch.setattr(ollama, "build_client", lambda *_a, **_kw: client)
    return {"client": client, "events": []}


@when("the researcher prepares and then stops the local service")
def prepare_and_stop_local_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unavailable_local_service: dict
) -> None:
    import subprocess

    import httpx

    from experiment.adapters import ollama

    state = unavailable_local_service
    state["running"] = ollama.serve_running()
    state["ready"] = ollama.wait_ready(attempts=2, sleep_s=0, sleep=lambda _s: None)
    state["pull"] = ollama.pull_model("/usr/bin/ollama", "qwen2.5:3b")
    state["digest"] = ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b")
    events = state["events"]

    class FakeProc:
        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> int:
            events.append(f"wait:{timeout}")
            raise subprocess.TimeoutExpired(cmd="ollama", timeout=timeout or 0)

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(ollama.subprocess, "Popen", lambda *_a, **_kw: FakeProc())
    owner = ollama.start_ollama("/usr/bin/ollama", tmp_path / "logs/ollama.log")
    assert owner is not None
    ollama.stop_ollama(owner)
    state["closed"] = owner.log_handle.closed

    def broken_call(*_a, **_kw):
        raise httpx.ConnectError("refused")

    with pytest.raises(ollama.HttpTransportError):
        ollama.request_with_retry(
            broken_call,
            "http://127.0.0.1:11434/v1/models",
            ollama.RetryPolicy(timeout=(1.0, 2.0), retries=0),
        )


@then("failures are reported and the owned service is stopped safely")
def local_service_failures_reported(unavailable_local_service: dict) -> None:
    state = unavailable_local_service
    assert state["running"] is False and state["ready"] is False
    assert state["pull"] == 1 and state["digest"] == "unavailable"
    assert state["events"] == ["terminate", "wait:10", "kill"]
    assert state["closed"] is True


# backend-preflight.feature — A hosted model recovers from rate limiting and hides an invalid
# credential


@given("a hosted model that first limits requests and then responds")
def hosted_model_is_available(fake_openrouter_sdk_client: MagicMock) -> None:
    assert fake_openrouter_sdk_client is not None


@when(
    "the researcher requests tool calls and later encounters an authentication failure",
    target_fixture="hosted_model_outcome",
)
def exercise_hosted_model(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
    rate_limit_error: OpenRouterError,
) -> dict:
    secret = "sk-or-v1-super-secret-value"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    is_hosted_profile = openrouter_adapter.is_openrouter_profile(openrouter_profile)

    fake_openrouter_sdk_client.chat.send.side_effect = [
        rate_limit_error,
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
                                "function": {"name": "relate_de9im", "arguments": '{"a": 1}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125},
        },
        {"choices": [{"message": {"role": "assistant", "content": "done"}}], "usage": None},
    ]

    gw = openrouter_adapter.OpenRouterChatGateway(
        openrouter_profile, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    reply1 = gw.complete([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    retry_calls = fake_openrouter_sdk_client.chat.send.call_count
    turn = gw.parse_turn(reply1)

    reply2 = gw.complete([{"role": "user", "content": "finish"}])
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    body = f"invalid key {secret}"
    auth_err = OpenRouterError(
        f"HTTP 401: {body}", raw_response=httpx.Response(401, text=body, request=req), body=body
    )
    fake_openrouter_sdk_client.chat.send.reset_mock()
    fake_openrouter_sdk_client.chat.send.side_effect = auth_err
    gw._secret = secret
    with pytest.raises(BackendError) as err401:
        gw.complete([{"role": "user", "content": "hi"}])
    return {
        "is_hosted_profile": is_hosted_profile,
        "retry_calls": retry_calls,
        "reply": reply1,
        "final": reply2,
        "calls": turn.tool_calls,
        "error_class": err401.value.error_class,
        "redacted": str(err401.value),
        "secret": secret,
        "auth_calls": fake_openrouter_sdk_client.chat.send.call_count,
    }


@then("tool use and response usage are preserved without exposing the credential")
def hosted_model_outcome_is_safe(hosted_model_outcome: dict) -> None:
    assert hosted_model_outcome["is_hosted_profile"] is True
    assert hosted_model_outcome["retry_calls"] == 2
    assert hosted_model_outcome["reply"]["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "total_tokens": 125,
    }
    call = hosted_model_outcome["calls"][0]
    assert call.name == "relate_de9im"
    assert call.call_id == "tc_1" and call.arguments == {"a": 1}
    assert "usage" not in hosted_model_outcome["final"]
    assert hosted_model_outcome["error_class"] == "http-401"
    assert hosted_model_outcome["secret"] not in hosted_model_outcome["redacted"]
    assert "[REDACTED]" in hosted_model_outcome["redacted"]
    assert hosted_model_outcome["auth_calls"] == 1


# backend-preflight.feature — A local model retries temporary overload and returns a tool call


@given("a local model endpoint experiencing temporary overload")
@given("a local model endpoint that rejects requests or times out")
def local_chat_endpoint(fake_ollama_sdk_client: MagicMock) -> None:
    assert fake_ollama_sdk_client is not None


@when("the researcher requests a tool call and a final answer", target_fixture="local_chat_outcome")
def exercise_local_chat(
    ollama_profile: BackendProfile,
    fake_ollama_sdk_client: MagicMock,
) -> dict:
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
    first_calls = fake_ollama_sdk_client.chat.call_count
    first_kwargs = fake_ollama_sdk_client.chat.call_args_list[0].kwargs

    gw = _ollama_chat.OllamaChatGateway(ollama_profile, client=fake_ollama_sdk_client)
    turn = gw.parse_turn(reply1)
    reply2 = gw.complete([{"role": "user", "content": "done"}])
    return {
        "turn": turn,
        "reply": reply1,
        "final": reply2,
        "first_calls": first_calls,
        "first_kwargs": first_kwargs,
    }


@then("the response retains the tool call and token usage")
def local_chat_preserves_usage(local_chat_outcome: dict) -> None:
    turn = local_chat_outcome["turn"]
    assert local_chat_outcome["first_calls"] == 2
    arguments = local_chat_outcome["first_kwargs"]["messages"][1]["tool_calls"][0]["function"]
    assert arguments["arguments"] == {"x": 1}
    assert local_chat_outcome["reply"]["usage"] == {
        "prompt_tokens": 40,
        "completion_tokens": 12,
        "total_tokens": 52,
    }
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "filter_features"
    assert turn.tool_calls[0].arguments == {"iso": "POL"}
    assert "usage" not in local_chat_outcome["final"]
    assert local_chat_outcome["final"]["choices"][0]["message"]["content"] == "final answer"


# backend-preflight.feature — Invalid requests and timeouts are reported by the local model


@when("the researcher requests a local model response", target_fixture="local_chat_errors")
def exercise_local_chat_failures(
    ollama_profile: BackendProfile,
    fake_ollama_sdk_client: MagicMock,
) -> tuple[str, int, str]:
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
    invalid_request_calls = fake_ollama_sdk_client.chat.call_count
    fake_ollama_sdk_client.chat.reset_mock()
    fake_ollama_sdk_client.chat.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(BackendError) as err_to:
        _ollama_chat.chat_completions_sdk(
            profile,
            [{"role": "user", "content": "hi"}],
            client=fake_ollama_sdk_client,
            sleep=lambda _s: None,
        )
    return err400.value.error_class, invalid_request_calls, err_to.value.error_class


@then("the failures are classified and invalid requests are not retried")
def local_chat_errors_classified(local_chat_errors: tuple[str, int, str]) -> None:
    assert local_chat_errors == ("http-400", 1, "timeout")


# backend-preflight.feature — Local model readiness survives temporary overload


@given("a local model readiness probe with a temporary service failure")
def local_probe_context(fake_ollama_sdk_client: MagicMock) -> None:
    assert fake_ollama_sdk_client is not None


@when(
    "the researcher probes the local model through its provider", target_fixture="provider_success"
)
def local_provider_readiness(
    ollama_profile: BackendProfile,
    fake_ollama_sdk_client: MagicMock,
) -> dict:
    profile = ollama_profile.model_copy(update={"retries": 1})
    fake_ollama_sdk_client.list.side_effect = [
        ollama_sdk.ResponseError("transient", status_code=503),
        {"models": [{"model": "qwen2.5:3b", "digest": "sha256:aaa111"}]},
        {"models": [{"model": "qwen2.5:3b", "digest": "sha256:aaa111"}]},
    ]
    fake_ollama_sdk_client.chat.return_value = {"message": {"role": "assistant", "content": "OK"}}

    probe = _sdk_probes.OllamaBackendProbe(
        profile, client=fake_ollama_sdk_client, sleep=lambda _s: None
    )
    models = probe.list_model_ids()
    digest = probe.resolve_model_digest()
    probe.verify_tiny_completion(max_tokens=8)
    list_calls = fake_ollama_sdk_client.list.call_count

    auth_client = MagicMock(name="ollama_auth_client")
    auth_client.list.side_effect = ollama_sdk.ResponseError("denied", status_code=401)
    auth_probe = _sdk_probes.OllamaBackendProbe(profile, client=auth_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_auth:
        auth_probe.list_model_ids()

    tok_client = MagicMock(name="ollama_tok_client")
    tok_client.chat.side_effect = ollama_sdk.ResponseError(
        "context length exceeded", status_code=400
    )
    tok_probe = _sdk_probes.OllamaBackendProbe(profile, client=tok_client, sleep=lambda _s: None)
    with pytest.raises(backend_probe.BackendProbeError) as e_tok:
        tok_probe.verify_tiny_completion(max_tokens=8)
    return {
        "models": models,
        "digest": digest,
        "list_calls": list_calls,
        "auth_kind": e_auth.value.kind,
        "auth_calls": auth_client.list.call_count,
        "token_kind": e_tok.value.kind,
    }


@then("the probe reports the model identity and classifies invalid requests")
def local_provider_probe_succeeded(provider_success: dict) -> None:
    assert provider_success == {
        "models": {"qwen2.5:3b"},
        "digest": "sha256:aaa111",
        "list_calls": 3,
        "auth_kind": "auth-error",
        "auth_calls": 1,
        "token_kind": "token-limit",
    }


# backend-preflight.feature — Provider readiness reports connection and response failures


@given("local and hosted model providers with simulated failures")
def failed_providers_context(
    fake_ollama_sdk_client: MagicMock, fake_openrouter_sdk_client: MagicMock
) -> None:
    assert fake_ollama_sdk_client is not None and fake_openrouter_sdk_client is not None


@when("the researcher checks both providers", target_fixture="provider_failures")
def provider_failure_checks(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    ollama_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
    fake_ollama_sdk_client: MagicMock,
    forbidden_openrouter_error: OpenRouterError,
) -> dict:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = openrouter_profile.model_copy(update={"retries": 0})
    ol_prof = ollama_profile.model_copy(update={"retries": 0})

    kinds = []
    for err in [forbidden_openrouter_error, httpx.ConnectError("offline")]:
        fake_openrouter_sdk_client.models.list.side_effect = err
        probe = _sdk_probes.OpenRouterBackendProbe(
            or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
        )
        with pytest.raises(backend_probe.BackendProbeError) as exc_info:
            probe.list_model_ids()
        kinds.append(exc_info.value.kind)

    fake_openrouter_sdk_client.chat.send.return_value = {"choices": []}
    empty_or = _sdk_probes.OpenRouterBackendProbe(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_empty:
        empty_or.verify_tiny_completion(max_tokens=8)
    kinds.append(e_empty.value.kind)

    fake_ollama_sdk_client.list.side_effect = httpx.ConnectError("down")
    conn_ol = _sdk_probes.OllamaBackendProbe(
        ol_prof, client=fake_ollama_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_ol_conn:
        conn_ol.list_model_ids()
    kinds.append(e_ol_conn.value.kind)

    fake_ollama_sdk_client.chat.return_value = {"message": {}}
    empty_ol = _sdk_probes.OllamaBackendProbe(
        ol_prof, client=fake_ollama_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(backend_probe.BackendProbeError) as e_ol_empty:
        empty_ol.verify_tiny_completion(max_tokens=8)
    kinds.append(e_ol_empty.value.kind)

    p_close = _sdk_probes.OpenRouterBackendProbe(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    p_close._owns_client = True
    p_close.close()
    return {"kinds": kinds, "client": fake_openrouter_sdk_client}


@then("their readiness failures are classified and owned resources are released")
def provider_failures_were_handled(provider_failures: dict) -> None:
    assert provider_failures["kinds"] == [
        "auth-error",
        "tunnel-dead",
        "completion-rejected",
        "tunnel-dead",
        "completion-rejected",
    ]
    provider_failures["client"].__exit__.assert_called_once()


# backend-preflight.feature — Explicit model settings override the local environment and saved
# profile


@given(
    "local and hosted service profiles and a local service environment setting",
    target_fixture="service_configuration",
)
def service_profiles_with_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    path = tmp_path / "services.toml"
    path.write_text(
        '[backends.local]\nbase_url = "http://from-file/v1"\nmodel = "file-model"\n'
        '[backends.free-open]\nbase_url = "http://remote/v1"\nmodel = "m"\n'
        'api_key_env = "X_TEST_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_HOST", "http://env:11434")
    return {"path": path}


@when("the researcher selects a local service with explicit host and model settings")
def select_explicit_service(service_configuration: dict) -> None:
    from experiment.adapters import backends

    path = service_configuration["path"]
    service_configuration["environment"] = backends.resolve_profile("local", path=path)
    service_configuration["hosted"] = backends.resolve_profile("free-open", path=path)
    service_configuration["explicit"] = backends.resolve_profile(
        "local", host="http://chosen:12345", model="chosen-model", path=path
    )


@then("the explicit settings take precedence over the environment and saved profile")
def explicit_service_takes_precedence(service_configuration: dict) -> None:
    assert str(service_configuration["environment"].base_url).rstrip("/") == "http://env:11434"
    explicit = service_configuration["explicit"]
    assert str(explicit.base_url).rstrip("/") == "http://chosen:12345"
    assert explicit.model == "chosen-model"


@then("the local environment does not change the hosted service")
def hosted_service_is_independent(service_configuration: dict) -> None:
    assert str(service_configuration["hosted"].base_url).rstrip("/") == "http://remote/v1"


# backend-preflight.feature — A local service has a safe default when configuration is absent


@given(
    "no saved service configuration or local service environment setting",
    target_fixture="service_configuration",
)
def missing_service_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    return {"path": tmp_path / "missing.toml"}


@when("the researcher selects the default local service")
def select_default_service(service_configuration: dict) -> None:
    from experiment.adapters import backends

    service_configuration["profile"] = backends.resolve_profile(
        "local", path=service_configuration["path"]
    )


@then("the default local address and model are used")
def default_service_is_available(service_configuration: dict) -> None:
    profile = service_configuration["profile"]
    assert str(profile.base_url).rstrip("/") == "http://127.0.0.1:11434"
    assert profile.model == "qwen2.5-coder:0.5b"


# backend-preflight.feature — Damaged or missing service configuration is reported


@given(parsers.parse("{problem} service configuration"), target_fixture="service_configuration")
def broken_service_configuration(problem: str, tmp_path: Path) -> dict:
    path = tmp_path / "services.toml"
    if problem == "malformed":
        path.write_text("[invalid\n", encoding="utf-8")
    return {"path": path}


@when("the researcher loads service configuration")
def load_broken_service_configuration(service_configuration: dict) -> None:
    from experiment.adapters import backends

    with pytest.raises(backends.BackendError) as error:
        backends.load_profiles(service_configuration["path"])
    service_configuration["error"] = error.value


@then("the configuration failure is reported")
def service_configuration_failure_reported(service_configuration: dict) -> None:
    assert "config" in str(service_configuration["error"])


# backend-preflight.feature — An unknown service profile names the available choice


@given("a saved model service profile", target_fixture="service_configuration")
def saved_service_profile(tmp_path: Path) -> dict:
    path = tmp_path / "services.toml"
    path.write_text(
        '[backends.demo]\nbase_url = "http://example.invalid/v1"\nmodel = "demo"\n',
        encoding="utf-8",
    )
    return {"path": path}


@when("the researcher selects an unknown service profile")
def select_unknown_profile(service_configuration: dict) -> None:
    from experiment.adapters import backends

    with pytest.raises(backends.BackendError) as error:
        backends.resolve_profile("nope", path=service_configuration["path"])
    service_configuration["error"] = error.value


@then("the error identifies the available profile")
def available_profile_named(service_configuration: dict) -> None:
    assert "demo" in str(service_configuration["error"])


# backend-preflight.feature — Hosted provider errors receive a matching diagnosis


@given(parsers.parse("a hosted provider reports {failure}"), target_fixture="hosted_failure")
def reported_hosted_failure(failure: str) -> tuple[OpenRouterError, bool]:
    cases = {
        "unauthorized credentials": (401, "unauthorized", False),
        "an exceeded context window": (400, "context_length exceeded", True),
        "an exhausted quota": (429, "quota", True),
        "a missing model": (404, "missing model", False),
        "an unavailable service": (502, "bad gateway", False),
    }
    status, body, completion = cases[failure]
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    error = OpenRouterError(
        f"HTTP {status}: {body}",
        raw_response=httpx.Response(status, text=body, request=request),
        body=body,
    )
    return error, completion


@when("the researcher checks the reported provider failure", target_fixture="hosted_diagnosis")
def diagnose_hosted_failure(
    hosted_failure: tuple[OpenRouterError, bool], openrouter_profile: BackendProfile
) -> str:
    error, completion = hosted_failure
    kind, _, _ = openrouter_adapter.classify_probe_error(
        error,
        openrouter_profile.model_copy(update={"retries": 0}),
        "sk-or-test-key",
        for_completion=completion,
    )
    return kind


@then(parsers.parse("the readiness diagnosis identifies {diagnosis}"))
def hosted_failure_is_diagnosed(hosted_diagnosis: str, diagnosis: str) -> None:
    assert (
        hosted_diagnosis
        == {
            "a credential problem": "auth-error",
            "a token limit": "token-limit",
            "a request problem": "client-error",
            "a connection problem": "tunnel-dead",
        }[diagnosis]
    )


# backend-preflight.feature — A ready backend is reported with its model identity


@given("the readiness check reports a pinned model is ready")
def ready_result_for_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from experiment.services import backend_check

    monkeypatch.setattr(
        backend_check,
        "run_backend_check",
        lambda _cfg: BackendCheckResult(
            status="READY",
            backend="remote-ollama",
            model="qwen2.5:3b",
            digest="sha256:pinned123",
            base_url="http://127.0.0.1:11435/v1",
        ),
    )


@when("I ask for a backend readiness report", target_fixture="cli_readiness")
def request_cli_readiness():
    from typer.testing import CliRunner

    from experiment.cli import app

    return CliRunner().invoke(app, ["env", "backend-check", "--ssh-host", "gpu-box"])


@then("the action succeeds")
def cli_readiness_succeeds(cli_readiness) -> None:
    assert cli_readiness.exit_code == 0, cli_readiness.output


@then("the report shows the ready model identity")
def cli_readiness_identity(cli_readiness) -> None:
    assert "READY" in cli_readiness.output and "sha256:pinned123" in cli_readiness.output


# backend-preflight.feature — A disconnected tunnel produces a failing readiness status


@given("the readiness check reports a disconnected tunnel")
def disconnected_result_for_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from experiment.services import backend_check

    def fail(_cfg):
        raise BackendCheckError("tunnel-dead", "socket closed", "restart ssh")

    monkeypatch.setattr(backend_check, "run_backend_check", fail)


@then("the readiness action reports a disconnected tunnel status")
def cli_readiness_disconnected(cli_readiness) -> None:
    assert cli_readiness.exit_code == EXIT_TUNNEL_DEAD


# backend-preflight.feature — A compatible service passes a complete readiness probe


@given("a compatible model service with a pinned model", target_fixture="compatible_service")
def compatible_model_service(respx_mock):
    import httpx

    chat = respx_mock.post("https://llm.example.invalid/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        )
    )
    tags = respx_mock.get("https://llm.example.invalid/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "qwen2.5:3b", "digest": "sha256:respx123"}]}
        )
    )
    models = respx_mock.get("https://llm.example.invalid/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen2.5:3b"}]})
    )
    return {"chat": chat, "tags": tags, "models": models}


@when("the researcher probes the available model and requests a test response")
def probe_compatible_service(compatible_service: dict) -> None:
    import httpx

    from experiment.adapters import backends

    profile = backends.fallback_profile("https://llm.example.invalid/v1", "qwen2.5:3b")
    with httpx.Client() as client:
        probe = HttpBackendProbe(profile, session=client, sleep=lambda _: None)
        compatible_service["models_found"] = probe.list_model_ids()
        compatible_service["pinned"] = probe.resolve_model_digest()
        probe.verify_tiny_completion(max_tokens=8)


@then("the probe identifies the model and its pinned version")
def compatible_probe_identifies_model(compatible_service: dict) -> None:
    assert "qwen2.5:3b" in compatible_service["models_found"]
    assert compatible_service["pinned"] == "sha256:respx123"
    assert compatible_service["models"].called and compatible_service["chat"].called


# backend-preflight.feature — A researcher gets a model reply and its version from the service


@when("the researcher requests a response and model identity")
def request_response_and_identity(compatible_service: dict) -> None:
    import httpx

    from experiment.adapters import backends

    profile = backends.fallback_profile("https://llm.example.invalid/v1", "qwen2.5:3b")
    with httpx.Client() as client:
        compatible_service["reply"] = backends.chat_completions(
            client, profile, [{"role": "user", "content": "hi"}]
        )
        compatible_service["digest"] = backends.resolve_model_digest(client, profile)


@then("the service returns the response and the pinned identity")
def response_and_identity_are_returned(compatible_service: dict) -> None:
    assert compatible_service["chat"].called
    assert compatible_service["tags"].called
    assert compatible_service["reply"]["choices"][0]["message"]["content"] == "OK"
    assert compatible_service["digest"] == "sha256:respx123"


# backend-preflight.feature — A model identity cannot be retrieved


@given(parsers.parse("a model service whose identity lookup encounters {problem}"))
def model_identity_lookup_failure(problem: str, fake_http_session: MagicMock) -> None:
    if problem == "a service error":
        fake_http_session.get.return_value = make_mock_response(500)
    elif problem == "an unreadable reply":
        fake_http_session.get.return_value = make_mock_response(200, ValueError("not json"))
    elif problem == "a disconnected service":
        fake_http_session.get.side_effect = httpx.ConnectError("down")
    else:
        raise ValueError(f"Unknown lookup problem: {problem}")


@when("the researcher requests the model identity", target_fixture="unavailable_model_identity")
def request_unavailable_model_identity(fake_http_session: MagicMock) -> str | None:
    from experiment.adapters import backends

    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")
    return backends.resolve_model_digest(fake_http_session, profile)


@then("no model version is reported")
def model_identity_unavailable(unavailable_model_identity: str | None) -> None:
    assert unavailable_model_identity is None


# backend-preflight.feature — The backend is temporarily overloaded and rate limited


@given("temporary overload followed by a rate-limited response")
def transient_errors(ok_http_session: MagicMock) -> None:
    models = [
        make_mock_response(503, text="overloaded"),
        make_mock_response(200, {"data": [{"id": "qwen2.5:3b"}]}),
    ]
    tags = make_mock_response(
        200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]}
    )
    ok_http_session.get.side_effect = lambda url, **_kw: (
        models.pop(0) if url.endswith("/v1/models") else tags
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


@then("the test response was requested twice")
def two_responses(ok_http_session: MagicMock) -> None:
    assert ok_http_session.post.call_count == 2


# backend-preflight.feature — The backend rejects the credentials


@given("the backend rejects the credentials")
def invalid_credentials(ok_http_session: MagicMock) -> None:
    ok_http_session.get.side_effect = None
    ok_http_session.get.return_value = make_mock_response(401, text="invalid api key")


@then("the report identifies a credentials error")
def auth_error(preflight: dict) -> None:
    assert_failure(preflight, "auth-error", EXIT_AUTH_CLIENT)


@then("the model list was requested only once")
def one_model_request(ok_http_session: MagicMock) -> None:
    assert ok_http_session.get.call_count == 1


# backend-preflight.feature — The requested response exceeds the model's limit


@given("the backend rejects the response as too long")
def response_too_long(ok_http_session: MagicMock) -> None:
    ok_http_session.post.return_value = make_mock_response(
        400, text="maximum context length / token limit exceeded"
    )


@then("the report identifies the model's token limit")
def token_error(preflight: dict) -> None:
    assert_failure(preflight, "token-limit", EXIT_TOKEN_LIMIT)


# backend-preflight.feature — The backend returns no usable response


@given("the backend returns an empty test response")
def empty_response(ok_http_session: MagicMock) -> None:
    ok_http_session.post.return_value = make_mock_response(200, {"choices": []})


@then("the report identifies a rejected response")
def completion_error(preflight: dict) -> None:
    assert_failure(preflight, "completion-rejected", EXIT_COMPLETION_REJECTED)


# backend-preflight.feature — A healthy connection and model can be checked independently


@given("a ready model and an available remote connection", target_fixture="independent_probes")
def independent_ready_probes(backend_check_config: BackendCheckConfig) -> dict:
    from experiment.services.backend_check import BackendProbe, TunnelProbe

    tunnel, probe = MagicMock(spec=TunnelProbe), MagicMock(spec=BackendProbe)
    probe.list_model_ids.return_value = {"qwen2.5:3b"}
    probe.resolve_model_digest.return_value = "sha256:pinned123"
    return {"config": backend_check_config, "tunnel": tunnel, "probe": probe}


@when("the researcher checks readiness through those connections")
def check_independent_readiness(independent_probes: dict) -> None:
    independent_probes["result"] = run_backend_check(
        independent_probes["config"],
        tunnel_probe=independent_probes["tunnel"],
        backend_probe=independent_probes["probe"],
        sleep=lambda _s: None,
    )


@then("the model is ready and a test response was requested")
def independent_readiness_verified(independent_probes: dict) -> None:
    config = independent_probes["config"]
    assert independent_probes["result"].status == "READY"
    independent_probes["tunnel"].verify.assert_called_once_with("gpu-box", config.control_path)
    independent_probes["probe"].verify_tiny_completion.assert_called_once_with(
        max_tokens=config.max_tokens
    )
    independent_probes["probe"].close.assert_not_called()


# backend-preflight.feature — Configuration and response errors receive distinct readiness statuses


@given("readiness checks with missing configuration or failed responses")
def readiness_failure_cases(backend_check_config: BackendCheckConfig) -> None:
    assert backend_check_config is not None


@when("the researcher checks those failure cases", target_fixture="readiness_failure_results")
def check_readiness_failure_cases(
    backend_check_config: BackendCheckConfig,
    fake_ssh_tunnel_adapter: SshTunnelAdapter,
    http_backend_probe: HttpBackendProbe,
    ok_http_session: MagicMock,
) -> list[tuple[int, int | None]]:
    import httpx

    results = []
    for updates in ({"ssh_host": None}, {"backend": "no-such-backend"}):
        with pytest.raises(BackendCheckError) as configuration_error:
            run_backend_check(
                backend_check_config.model_copy(update=updates),
                tunnel_probe=fake_ssh_tunnel_adapter,
                sleep=lambda _s: None,
            )
        results.append((backend_check_exit_code(configuration_error.value.kind), None))
    ok_http_session.get.side_effect = httpx.ConnectError("refused")
    with pytest.raises(BackendCheckError) as connection_error:
        run_backend_check(
            backend_check_config,
            tunnel_probe=fake_ssh_tunnel_adapter,
            backend_probe=http_backend_probe,
            sleep=lambda _s: None,
        )
    results.append((backend_check_exit_code(connection_error.value.kind), None))
    models = make_mock_response(200, {"data": [{"id": "qwen2.5:3b"}]})
    tags = make_mock_response(
        200, {"models": [{"name": "qwen2.5:3b", "digest": "sha256:pinned123"}]}
    )
    ok_http_session.get.side_effect = lambda url, **_kw: (
        models if url.endswith("/v1/models") else tags
    )
    for status, text in ((429, "quota"), (401, "denied"), (500, "crash")):
        ok_http_session.post.reset_mock()
        ok_http_session.post.return_value = make_mock_response(status, text=text)
        with pytest.raises(BackendCheckError) as response_error:
            run_backend_check(
                backend_check_config,
                tunnel_probe=fake_ssh_tunnel_adapter,
                backend_probe=http_backend_probe,
                sleep=lambda _s: None,
            )
        results.append(
            (backend_check_exit_code(response_error.value.kind), ok_http_session.post.call_count)
        )
    return results


@then("each failure reports its proper status and retry count")
def failure_statuses_and_retries(readiness_failure_results: list[tuple[int, int | None]]) -> None:
    assert readiness_failure_results == [
        (EXIT_SSH_UNREACHABLE, None),
        (EXIT_AUTH_CLIENT, None),
        (EXIT_TUNNEL_DEAD, None),
        (EXIT_TOKEN_LIMIT, 4),
        (EXIT_AUTH_CLIENT, 1),
        (EXIT_COMPLETION_REJECTED, 4),
    ]


# backend-preflight.feature — A hosted provider can report readiness


@given("a hosted provider with the requested model", target_fixture="hosted_ready_probe")
def hosted_provider_with_model(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
) -> dict:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    profile = openrouter_profile.model_copy(update={"retries": 0})
    fake_openrouter_sdk_client.models.list.return_value = {
        "result": {"data": [{"id": profile.model}]}
    }
    probe = _sdk_probes.OpenRouterBackendProbe(
        profile, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    return {"probe": probe, "model": profile.model}


@when("the researcher checks that provider's readiness")
def check_hosted_provider(hosted_ready_probe: dict) -> None:
    hosted_ready_probe["result"] = run_backend_check(
        BackendCheckConfig(backend="free-open", poll_timeout_s=0.05, poll_interval_s=0.0),
        backend_probe=hosted_ready_probe["probe"],
        sleep=lambda _s: None,
    )


@then("the hosted provider is ready with the model identity")
def hosted_provider_ready(hosted_ready_probe: dict) -> None:
    assert hosted_ready_probe["result"].status == "READY"
    assert hosted_ready_probe["result"].digest == hosted_ready_probe["model"]


# backend-preflight.feature — A configured remote connection is opened and closed


@given("a remote connection with a named user and custom port")
def configured_remote_connection(preflight: dict, fake_ssh_forwarder: MagicMock) -> None:
    preflight["forwarder"] = fake_ssh_forwarder
    preflight["forwarder"].local_bind_port = 41234


@when("the researcher opens and closes the connection")
def use_remote_connection(preflight: dict) -> None:
    from experiment.adapters.ssh_tunnel import ManagedSshTunnel, TunnelSpec

    def factory(**kwargs: object) -> MagicMock:
        preflight["connection_options"] = kwargs
        return preflight["forwarder"]

    with ManagedSshTunnel(
        TunnelSpec(ssh_host="alice@gpu.example.org:2222", ssh_password="pw"),
        forwarder_factory=factory,
    ) as tunnel:
        preflight["active_during_use"] = tunnel.is_active
        preflight["port_during_use"] = tunnel.local_bind_port
    preflight["tunnel"] = tunnel


@then("the connection uses the requested remote host and user")
def connection_target(preflight: dict) -> None:
    assert preflight["connection_options"]["ssh_address_or_host"] == ("gpu.example.org", 2222)
    assert preflight["connection_options"]["ssh_username"] == "alice"
    preflight["forwarder"].start.assert_called_once()
    assert preflight["active_during_use"]
    assert preflight["port_during_use"] == 41234


@then("its local port is released after use")
def connection_released(preflight: dict) -> None:
    preflight["forwarder"].stop.assert_called_once()
    assert preflight["tunnel"].local_bind_port is None
    assert not preflight["tunnel"].is_active


# backend-preflight.feature — Port forwarding fails while opening a remote connection


@given("a remote connection whose forwarding cannot start")
def forwarding_failure(fake_ssh_forwarder: MagicMock) -> None:
    fake_ssh_forwarder.start.side_effect = sshtunnel.HandlerSSHTunnelForwarderError("bind refused")


# backend-preflight.feature — Remote connection authentication fails


@given("a remote connection that rejects authentication")
def ssh_authentication_failure(fake_ssh_forwarder: MagicMock) -> None:
    import paramiko

    fake_ssh_forwarder.start.side_effect = paramiko.SSHException("auth failed")
