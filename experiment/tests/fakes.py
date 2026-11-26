"""Shared ``unittest.mock``-based fake fixtures for the experiment test suite.

Re-exported by ``conftest.py`` so every unit test module can inject fakes as
standard pytest fixtures instead of hand-rolling stub classes.
"""

from __future__ import annotations

import io
import json
import sys
import types
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_mock import MockerFixture

from experiment.adapters import backends
from experiment.adapters.backend_probe import HttpBackendProbe
from experiment.adapters.ssh_tunnel import SshTunnelAdapter
from experiment.adapters.subprocess_runner import CommandResult
from experiment.domain.prompts import SandboxExecution
from experiment.services.backend_check import BackendCheckConfig
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
    """Configure a ``MagicMock(spec=httpx.Response)`` for HTTP tests."""
    response = MagicMock(spec=httpx.Response)
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
def fake_ollama_sdk_client(mocker: MockerFixture) -> MagicMock:
    """Mock Ollama SDK client with ``.chat``, ``.list``, ``.show``, ``.ps``, ``.pull``."""
    client = mocker.MagicMock(name="ollama_sdk_client")
    client.list.return_value = {"models": []}
    client.chat.return_value = {
        "message": {"role": "assistant", "content": "OK"},
        "done_reason": "stop",
    }
    return client


@pytest.fixture
def fake_openrouter_sdk_client(mocker: MockerFixture) -> MagicMock:
    """Mock OpenRouter SDK client supporting ``chat.send``, ``models.list``, and context exit."""
    client = mocker.MagicMock(name="openrouter_sdk_client")
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.chat = mocker.MagicMock(name="openrouter_chat")
    client.models = mocker.MagicMock(name="openrouter_models")
    client.chat.send.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]
    }
    client.models.list.return_value = {"data": []}
    return client


@pytest.fixture
def fake_http_response() -> MagicMock:
    """Default 200 OK ``MagicMock(spec=httpx.Response)``."""
    return make_mock_response(200, {})


@pytest.fixture
def fake_http_session(mocker: MockerFixture, fake_http_response: MagicMock) -> MagicMock:
    """``MagicMock(spec=httpx.Client)`` wired with default ``get``/``post`` responses."""
    session = mocker.MagicMock(spec=httpx.Client)
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.get.return_value = fake_http_response
    session.post.return_value = fake_http_response
    return session


@pytest.fixture
def fake_ssh_forwarder(mocker: MockerFixture) -> MagicMock:
    """``MagicMock`` SSH tunnel forwarder tracking ``start``/``stop`` and active state."""
    forwarder = mocker.MagicMock(name="ssh_forwarder")
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


def _wrap_in_outer_artifact_zip(inner_zip: Path, member_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, inner_zip.read_bytes())
    return buf.getvalue()


@pytest.fixture
def fake_pygithub(packed_pilot_zip: Path) -> tuple[MagicMock, MagicMock]:
    """Return ``(github_client, http_client)`` mocks simulating PyGithub + 302 artifact redirect."""
    run = MagicMock(name="workflow_run")
    run.id = 987654321
    run.head_sha = "deadbeef"
    run.status = "completed"
    run.conclusion = "success"
    run.created_at = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    run.display_title = "Experiment"
    run.html_url = "https://github.com/org/repo/actions/runs/987654321"

    artifact = MagicMock(name="artifact")
    artifact.name = "experiment-run-987654321-deadbeef"
    artifact.expired = False
    artifact.archive_download_url = (
        "https://api.github.com/repos/Archont561/geoai-mcp-eval/actions/artifacts/555/zip"
    )
    run.get_artifacts.return_value = [artifact]

    workflow = MagicMock(name="workflow")
    workflow.get_runs.return_value = [run]

    repo = MagicMock(name="repo")
    repo.get_workflow.return_value = workflow
    repo.get_workflow_run.return_value = run

    gh = MagicMock(name="github_client")
    gh.get_repo.return_value = repo

    outer_bytes = _wrap_in_outer_artifact_zip(
        packed_pilot_zip, "experiment-run-987654321-deadbeef.zip"
    )
    redirect_resp = MagicMock(spec=httpx.Response)
    redirect_resp.status_code = 302
    redirect_resp.headers = {"location": "https://blob.example.invalid/sas-artifact.zip"}
    redirect_resp.content = b""

    blob_resp = MagicMock(spec=httpx.Response)
    blob_resp.status_code = 200
    blob_resp.headers = {}
    blob_resp.content = outer_bytes

    def http_get(url: str, **_kwargs: Any) -> MagicMock:
        if "api.github.com" in url:
            return redirect_resp
        return blob_resp

    http_client = MagicMock(spec=httpx.Client)
    http_client.get.side_effect = http_get
    return gh, http_client


def clear_library_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GDAL_VERSION", "GEOS_VERSION", "PROJ_VERSION"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def fake_current_gis_host(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_library_overrides(monkeypatch)
    core = types.ModuleType("qgis.core")

    class FakeQgis:
        @staticmethod
        def version() -> str:
            return "4.2.3-Belém do Pará"

        @staticmethod
        def geosVersion() -> str:
            return "3.14.1-CAPI-1.20.5"

    core.Qgis = FakeQgis
    osgeo = types.ModuleType("osgeo")
    gdal = types.ModuleType("osgeo.gdal")
    gdal.VersionInfo = lambda req="RELEASE_NAME": "3.13.3" if req == "RELEASE_NAME" else ""
    osr = types.ModuleType("osgeo.osr")
    osr.GetPROJVersionMajor = lambda: 9
    osr.GetPROJVersionMinor = lambda: 9
    osr.GetPROJVersionMicro = lambda: 0
    osgeo.gdal, osgeo.osr = gdal, osr
    for name, module in (
        ("qgis.core", core),
        ("osgeo", osgeo),
        ("osgeo.gdal", gdal),
        ("osgeo.osr", osr),
    ):
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def fake_legacy_gis_host(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_library_overrides(monkeypatch)
    core = types.ModuleType("qgis.core")
    core.QGIS_VERSION = "3.40.0"

    class FakeProjUtils:
        @staticmethod
        def projVersionMajor() -> int:
            return 9

        @staticmethod
        def projVersionMinor() -> int:
            return 8

    core.QgsProjUtils = FakeProjUtils
    monkeypatch.setitem(sys.modules, "qgis.core", core)
    for name in ("osgeo", "osgeo.gdal", "osgeo.osr"):
        monkeypatch.setitem(sys.modules, name, None)


@pytest.fixture
def fake_missing_gis_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a machine without the GIS host libraries."""
    monkeypatch.setitem(sys.modules, "qgis.core", None)
