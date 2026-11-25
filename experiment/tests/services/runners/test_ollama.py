"""Unit tests for ``experiment.services.runners.ollama``."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml

from experiment.adapters import backends, harness_io, task_repository
from experiment.adapters.mcp.client import McpToolSession
from experiment.domain.cache_key import CacheStats
from experiment.domain.prompts import ChatTurn, SandboxExecution
from experiment.domain.task import Task
from experiment.services import runs
from experiment.services.runners import ollama_arm_a, ollama_arm_b
from experiment.services.runners.ports import CellRequest, HarnessPorts

TASK_ROOT = harness_io.TASK_ROOT
FINAL_JSON = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'


def _task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if yaml.safe_load(path.read_text(encoding="utf-8"))["id"] == task_id:
            return path
    raise AssertionError(task_id)


def _fixture(task_id: str) -> dict:
    task = task_repository.load_task(_task_path(task_id))
    return json.loads(
        (harness_io.fixture_path(_task_path(task_id), task)).read_text(encoding="utf-8")
    )


def _cell_request(
    task_id: str, arm: str, driver: str, cell: Path, run_id: str = "test"
) -> CellRequest:
    task_path = _task_path(task_id)
    task = task_repository.load_task(task_path)
    return CellRequest(
        task_path=task_path,
        task=task,
        arm=arm,
        driver=driver,
        cell=cell,
        model="fake",
        host="http://x",
        run_id=run_id,
    )


def _tool_call_response(name: str, arguments: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                }
            }
        ]
    }


def _content_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _install_fake_chat(monkeypatch: pytest.MonkeyPatch, responder) -> None:
    monkeypatch.setattr(backends, "chat_completions", lambda *_a, **_kw: responder())


class _FakeChatGateway:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []
        self.closed = False

    @property
    def temperature(self) -> float:
        return 0.0

    @property
    def max_tokens(self) -> int:
        return 1024

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((list(messages), tools))
        return self._replies.pop(0)

    def parse_turn(self, reply: dict[str, Any]) -> ChatTurn:
        return backends.parse_chat_turn(reply)

    def close(self) -> None:
        self.closed = True


class _FakeToolSession:
    def __init__(self) -> None:
        self.invocations: list[tuple[str, dict[str, Any]]] = []
        self.opened = 0
        self.closed = 0

    def list_tool_specs(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": "feature_info", "parameters": {}}}]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.invocations.append((name, arguments))
        return {"feature_count": 2}


class _FakeSandbox:
    def __init__(self, result: SandboxExecution) -> None:
        self._result = result
        self.executed: list[tuple[str, Path | None]] = []

    def execute(
        self,
        code: str,
        *,
        fixture_src: Path | None = None,
        timeout_s: int = 120,
    ) -> SandboxExecution:
        self.executed.append((code, fixture_src))
        return self._result


class _FakeWorkspace:
    def __init__(self, fixture: dict[str, Any], fixture_path: Path | None = None) -> None:
        self._fixture = fixture
        self._fixture_path = fixture_path or Path("/fake/fixture.geojson")
        self.transcript: list[dict[str, Any]] = []
        self.deliverables: list[Any] = []

    def resolve_fixture(self, task_path: Path, task: Task) -> Path:
        return self._fixture_path

    def load_fixture(self, task_path: Path, task: Task) -> dict[str, Any]:
        return self._fixture

    def append_transcript(self, cell: Path, record: dict[str, Any]) -> None:
        self.transcript.append(record)

    def write_deliverable(self, cell: Path, task: Task, payload: Any) -> Path:
        self.deliverables.append(payload)
        return cell / "result.json"


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def put(self, key: str, reply: dict[str, Any]) -> None:
        self._store[key] = reply


def _port_request(tmp_path: Path, arm: str, *, model_digest: str | None = None) -> CellRequest:
    task_path = TASK_ROOT / "analysis-de9im-001.yaml"
    task = task_repository.load_task(task_path)
    cell = tmp_path / f"cell-{arm}"
    cell.mkdir(parents=True, exist_ok=True)
    return CellRequest(
        task_path=task_path,
        task=task,
        arm=arm,
        driver="ollama",
        cell=cell,
        model="fake",
        host="http://fake",
        run_id="port-test",
        model_digest=model_digest,
        cache_stats=CacheStats(),
    )


def test_arm_a_runs_purely_through_injected_ports_with_single_tool_session(
    tmp_path: Path,
) -> None:
    chat = _FakeChatGateway(
        [
            _tool_call_response("feature_info", "{}"),
            _content_response(FINAL_JSON),
        ]
    )
    tool_session = _FakeToolSession()

    @contextmanager
    def open_tools():
        tool_session.opened += 1
        try:
            yield tool_session
        finally:
            tool_session.closed += 1

    workspace = _FakeWorkspace({"type": "FeatureCollection", "features": []})
    ports = HarnessPorts(
        chat=chat,
        open_tools=open_tools,
        sandbox=_FakeSandbox(SandboxExecution(returncode=0, stdout="", stderr="")),
        workspace=workspace,
    )
    ollama_arm_a(_port_request(tmp_path, "A"), ports=ports)
    assert tool_session.opened == 1
    assert tool_session.closed == 1
    assert tool_session.invocations == [("feature_info", {})]
    assert workspace.deliverables == [{"relation": "touches", "de9im": "FF2F11212"}]
    assert chat.closed is False


def test_arm_b_runs_purely_through_injected_ports_and_cache(tmp_path: Path) -> None:
    reply = {
        "choices": [
            {"message": {"role": "assistant", "content": "```python\nprint('{\"ok\": 1}')\n```"}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }
    chat = _FakeChatGateway([reply])
    sandbox = _FakeSandbox(SandboxExecution(returncode=0, stdout='{"ok": 1}\n', stderr=""))
    workspace = _FakeWorkspace({"type": "FeatureCollection", "features": []})
    cache = _FakeCache()
    ports = HarnessPorts(
        chat=chat,
        open_tools=McpToolSession,
        sandbox=sandbox,
        workspace=workspace,
        cache=cache,
    )
    req1 = _port_request(tmp_path, "B", model_digest="sha256:pin")
    ollama_arm_b(req1, ports=ports)
    assert sandbox.executed == [("print('{\"ok\": 1}')\n", Path("/fake/fixture.geojson"))]
    assert workspace.deliverables == [{"ok": 1}]
    assert len(chat.calls) == 1

    req2 = _port_request(tmp_path, "B", model_digest="sha256:pin")
    ollama_arm_b(req2, ports=ports)
    assert len(chat.calls) == 1
    assert req2.cache_stats is not None and req2.cache_stats.hits == 1


def test_ollama_arm_a_tool_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixture = _fixture("analysis-de9im-001")
    args = json.dumps({"geojson": fixture, "property": "ISO_A3", "equals": "POL"})
    calls = {"n": 0}

    def responder() -> dict:
        calls["n"] += 1
        return (
            _tool_call_response("feature_info", args)
            if calls["n"] == 1
            else _content_response(FINAL_JSON)
        )

    _install_fake_chat(monkeypatch, responder)
    cell = tmp_path / "cell"
    cell.mkdir()
    result = runs.run_cell(_cell_request("analysis-de9im-001", "A", "ollama", cell))
    assert result["status"] == "ok"
    assert result["oracle_passed"] is True
    assert "feature_info" in (cell / "transcript.jsonl").read_text(encoding="utf-8")


def test_ollama_arm_a_tool_error_is_captured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"n": 0}

    def responder() -> dict:
        calls["n"] += 1
        return (
            _tool_call_response("no_such_tool", "{}")
            if calls["n"] == 1
            else _content_response(FINAL_JSON)
        )

    _install_fake_chat(monkeypatch, responder)
    cell = tmp_path / "cell"
    cell.mkdir()
    result = runs.run_cell(_cell_request("analysis-de9im-001", "A", "ollama", cell))
    assert result["status"] == "ok"
    assert "no_such_tool" in (cell / "transcript.jsonl").read_text(encoding="utf-8")


def test_ollama_arm_b_executes_code_and_handles_fences(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = (
        "import json, os\n"
        "assert os.listdir('.') == ['input.geojson']\n"
        "fx = json.load(open('input.geojson'))\n"
        "assert fx['type'] == 'FeatureCollection'\n"
        "print(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    )
    _install_fake_chat(monkeypatch, lambda: _content_response(f"```python\n{code}```"))
    cell = tmp_path / "ok"
    cell.mkdir()
    result = runs.run_cell(_cell_request("analysis-de9im-001", "B", "ollama", cell))
    assert result["oracle_passed"] is True
    assert not (cell / "input.geojson").exists()

    _install_fake_chat(monkeypatch, lambda: _content_response("no code here, sorry"))
    bad = tmp_path / "bad"
    bad.mkdir()
    assert (
        runs.run_cell(_cell_request("analysis-de9im-001", "B", "ollama", bad))["oracle_passed"]
        is False
    )

    _install_fake_chat(monkeypatch, lambda: _content_response(FINAL_JSON))
    jf = tmp_path / "json-fence"
    jf.mkdir()
    res_jf = runs.run_cell(_cell_request("analysis-de9im-001", "B", "ollama", jf))
    assert res_jf["oracle_passed"] is False
    assert not (jf / "result.json").exists()
    transcript = (jf / "transcript.jsonl").read_text(encoding="utf-8")
    assert "no python block found" in transcript and "<string>" not in transcript

    short_code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    for label, fence in (("py", f"```py\n{short_code}```"), ("raw", f"```\n{short_code}```")):
        _install_fake_chat(monkeypatch, lambda f=fence: _content_response(f))
        c = tmp_path / label
        c.mkdir()
        assert (
            runs.run_cell(_cell_request("analysis-de9im-001", "B", "ollama", c))["oracle_passed"]
            is True
        )


def test_ollama_arm_a_sums_multiturn_usage_and_aborts_on_token_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_path = _task_path("analysis-de9im-001")
    task = task_repository.load_task(task_path)
    fixture = _fixture("analysis-de9im-001")
    args = json.dumps({"geojson": fixture, "property": "ISO_A3", "equals": "POL"})
    calls = {"n": 0}

    def responder_ok(*_args, **_kwargs) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                **_tool_call_response("feature_info", args),
                "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
            }
        return {
            **_content_response(FINAL_JSON),
            "usage": {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
        }

    monkeypatch.setattr(backends, "chat_completions", responder_ok)
    cell_ok = tmp_path / "ok"
    cell_ok.mkdir()
    res_ok = runs.run_cell(
        CellRequest(
            task_path=task_path,
            task=task,
            arm="A",
            driver="ollama",
            cell=cell_ok,
            model="fake",
            host="http://x",
            run_id="r1",
            max_cell_tokens=250,
        )
    )
    assert res_ok["status"] == "ok"
    assert res_ok["usage"]["total_tokens"] == 200

    tool_invoked = {"called": False}

    def fail_if_called(*_args, **_kwargs):
        tool_invoked["called"] = True
        raise AssertionError("MCP tool must not execute after token cap is exceeded")

    monkeypatch.setattr(McpToolSession, "call_tool", fail_if_called)
    calls["n"] = 0
    cell_cap = tmp_path / "cap"
    cell_cap.mkdir()
    res_cap = runs.run_cell(
        CellRequest(
            task_path=task_path,
            task=task,
            arm="A",
            driver="ollama",
            cell=cell_cap,
            model="fake",
            host="http://x",
            run_id="r2",
            max_cell_tokens=50,
        )
    )
    assert res_cap["status"] == "aborted"
    assert res_cap["abort_reason"] == "token_cap_exceeded"
    assert tool_invoked["called"] is False
    assert res_cap["usage"]["total_tokens"] == 80
    assert res_cap["usage"]["cap_exceeded"] is True
