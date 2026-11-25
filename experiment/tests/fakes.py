"""Shared ``unittest.mock``-based fake fixtures for the experiment test suite.

Re-exported by ``conftest.py`` so every unit test module can inject fakes as
standard pytest fixtures instead of hand-rolling stub classes.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from experiment.adapters import backends
from experiment.adapters.ssh_tunnel import SshTunnelAdapter
from experiment.adapters.subprocess_runner import CommandResult
from experiment.domain.prompts import SandboxExecution
from experiment.services.runners.ports import (
    CellWorkspace,
    ChatGateway,
    CodeSandbox,
    CompletionCachePort,
    HarnessPorts,
    ToolSession,
)


def make_mock_response(
    status_code: int = 200,
    payload: Any = None,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Configure a ``MagicMock(spec=requests.Response)`` for HTTP tests."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.headers = dict(headers or {})
    if text:
        response.text = text
    elif payload is None:
        response.text = ""
    elif isinstance(payload, Exception):
        response.text = str(payload)
    else:
        response.text = json.dumps(payload)
    if isinstance(payload, Exception):
        response.json.side_effect = payload
    else:
        response.json.return_value = payload
    return response


@pytest.fixture
def fake_ollama_sdk_client() -> MagicMock:
    """Mock Ollama SDK client with ``.chat``, ``.list``, ``.show``, ``.ps``, ``.pull``."""
    client = MagicMock(name="ollama_sdk_client")
    client.list.return_value = {"models": []}
    client.chat.return_value = {
        "message": {"role": "assistant", "content": "OK"},
        "done_reason": "stop",
    }
    return client


@pytest.fixture
def fake_openrouter_sdk_client() -> MagicMock:
    """Mock OpenRouter SDK client supporting ``chat.send``, ``models.list``, and context exit."""
    client = MagicMock(name="openrouter_sdk_client")
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.chat = MagicMock(name="openrouter_chat")
    client.models = MagicMock(name="openrouter_models")
    client.chat.send.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]
    }
    client.models.list.return_value = {"data": []}
    return client


@pytest.fixture
def fake_http_response() -> MagicMock:
    """Default 200 OK ``MagicMock(spec=requests.Response)``."""
    return make_mock_response(200, {})


@pytest.fixture
def fake_http_session(fake_http_response: MagicMock) -> MagicMock:
    """``MagicMock(spec=requests.Session)`` wired with default ``get``/``post`` responses."""
    session = MagicMock(spec=requests.Session)
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.get.return_value = fake_http_response
    session.post.return_value = fake_http_response
    return session


@pytest.fixture
def fake_ssh_forwarder() -> MagicMock:
    """``MagicMock`` SSH tunnel forwarder tracking ``start``/``stop`` and active state."""
    forwarder = MagicMock(name="ssh_forwarder")
    forwarder.is_active = True
    forwarder.local_bind_port = 44556
    return forwarder


@pytest.fixture
def fake_ssh_tunnel_adapter(fake_ssh_forwarder: MagicMock) -> SshTunnelAdapter:
    """``SshTunnelAdapter`` backed by ``fake_ssh_forwarder``."""
    return SshTunnelAdapter(forwarder_factory=lambda **_kw: fake_ssh_forwarder)


@pytest.fixture
def fake_chat_gateway() -> MagicMock:
    """``MagicMock(spec=ChatGateway)`` parsing replies via ``backends.parse_chat_turn``."""
    gateway = MagicMock(spec=ChatGateway)
    gateway.temperature = 0.0
    gateway.max_tokens = 1024
    gateway.parse_turn.side_effect = backends.parse_chat_turn
    gateway.complete.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}}]
    }
    return gateway


@pytest.fixture
def fake_tool_session() -> MagicMock:
    """``MagicMock(spec=ToolSession)`` with one advertised tool and a default reply."""
    session = MagicMock(spec=ToolSession)
    session.list_tool_specs.return_value = [
        {"type": "function", "function": {"name": "feature_info", "parameters": {}}}
    ]
    session.call_tool.return_value = {"feature_count": 2}
    return session


@pytest.fixture
def fake_code_sandbox() -> MagicMock:
    """``MagicMock(spec=CodeSandbox)`` returning a clean zero-exit ``SandboxExecution``."""
    sandbox = MagicMock(spec=CodeSandbox)
    sandbox.execute.return_value = SandboxExecution(returncode=0, stdout="", stderr="")
    return sandbox


@pytest.fixture
def fake_cell_workspace(tmp_path: Path) -> MagicMock:
    """``MagicMock(spec=CellWorkspace)`` recording transcript entries and deliverables."""
    workspace = MagicMock(spec=CellWorkspace)
    workspace.fixture_data = {"type": "FeatureCollection", "features": []}
    workspace.fixture_path = tmp_path / "fixture.geojson"
    workspace.transcript = []
    workspace.deliverables = []
    workspace.resolve_fixture.side_effect = lambda _p, _t: workspace.fixture_path
    workspace.load_fixture.side_effect = lambda _p, _t: workspace.fixture_data
    workspace.append_transcript.side_effect = lambda _cell, rec: workspace.transcript.append(rec)

    def _write_deliverable(cell: Path, _task: Any, payload: Any) -> Path:
        workspace.deliverables.append(payload)
        return cell / "result.json"

    workspace.write_deliverable.side_effect = _write_deliverable
    return workspace


@pytest.fixture
def fake_completion_cache() -> MagicMock:
    """``MagicMock(spec=CompletionCachePort)`` backed by an in-memory dictionary."""
    store: dict[str, dict[str, Any]] = {}
    cache = MagicMock(spec=CompletionCachePort)
    cache.store = store
    cache.get.side_effect = store.get
    cache.put.side_effect = lambda key, reply: store.__setitem__(key, reply)
    return cache


@pytest.fixture
def fake_harness_ports(
    fake_chat_gateway: MagicMock,
    fake_tool_session: MagicMock,
    fake_code_sandbox: MagicMock,
    fake_cell_workspace: MagicMock,
    fake_completion_cache: MagicMock,
) -> HarnessPorts:
    """``HarnessPorts`` assembled entirely from ``unittest.mock`` fake fixtures."""
    open_tracker = MagicMock(name="open_tools_tracker")

    @contextmanager
    def _open_tools():
        open_tracker.open()
        try:
            yield fake_tool_session
        finally:
            open_tracker.close()

    fake_tool_session.lifecycle = open_tracker
    return HarnessPorts(
        chat=fake_chat_gateway,
        open_tools=_open_tools,
        sandbox=fake_code_sandbox,
        workspace=fake_cell_workspace,
        cache=fake_completion_cache,
    )


@pytest.fixture
def fake_subprocess_runner() -> MagicMock:
    """``MagicMock`` subprocess runner returning a zero-exit ``CommandResult``."""
    runner = MagicMock(name="subprocess_runner")
    runner.return_value = CommandResult(returncode=0, stdout="", stderr="")
    return runner
