"""Unit tests for ``experiment.adapters.openrouter``."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters import openrouter as openrouter_adapter
from experiment.domain.backend import BackendError, BackendProfile


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    case=st.sampled_from(
        [
            (httpx.ReadTimeout, "timeout"),
            (httpx.ConnectError, "connection"),
            (httpx.ProtocolError, "transport"),
        ]
    ),
    detail=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20),
)
def test_openrouter_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    fake_openrouter_sdk_client: MagicMock,
    case: tuple[type[Exception], str],
    detail: str,
) -> None:
    exc_type, expected_cls = case
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    or_prof = openrouter_profile.model_copy(update={"retries": 0})
    fake_openrouter_sdk_client.chat.send.reset_mock(side_effect=True)
    fake_openrouter_sdk_client.chat.send.side_effect = exc_type(detail)
    gw = openrouter_adapter.OpenRouterChatGateway(
        or_prof, client=fake_openrouter_sdk_client, sleep=lambda _s: None
    )
    with pytest.raises(BackendError) as err_chat:
        gw.complete([{"role": "user", "content": "hi"}])
    assert err_chat.value.error_class == expected_cls
