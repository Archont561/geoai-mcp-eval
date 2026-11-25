"""Tests for Clean Architecture harness ports, pure prompt parsers, and persistent MCP sessions."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from experiment.adapters import backends, harness_io, task_repository
from experiment.adapters.mcp.client import McpToolSession
from experiment.domain.cache_key import CacheStats
from experiment.domain.prompts import (
    ARM_A_SYSTEM_PROMPT,
    ARM_B_SYSTEM_PROMPT,
    ChatTurn,
    SandboxExecution,
    extract_python_code_block,
    extract_stdout_json,
    prompt_sha256,
)
from experiment.domain.task import Task
from experiment.services.runners import ollama_arm_a, ollama_arm_b
from experiment.services.runners.ports import CellRequest, HarnessPorts

RATIFIED_ARM_B_SHA256 = "5c44378126c5b889a159b7524ea83bf0d365f45854ee2559b38230851ac1c985"


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


def _real_request(tmp_path: Path, arm: str, *, model_digest: str | None = None) -> CellRequest:
    task_path = harness_io.TASK_ROOT / "analysis-de9im-001.yaml"
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


def test_ratified_prompt_scaffolds_are_preserved_verbatim() -> None:
    assert prompt_sha256(ARM_B_SYSTEM_PROMPT) == RATIFIED_ARM_B_SHA256
    assert len(ARM_B_SYSTEM_PROMPT.encode("utf-8")) == 418
    assert "provided tools only" in ARM_A_SYSTEM_PROMPT
    assert len(prompt_sha256(ARM_A_SYSTEM_PROMPT)) == 64


def test_pure_parsers_and_wire_translation() -> None:
    assert extract_stdout_json('{"relation": "touches"}\n') == {"relation": "touches"}
    assert extract_stdout_json('warning line\n{"ok": true}') == {"ok": True}
    assert extract_stdout_json('```json\n{"x": 1}\n```') == {"x": 1}
    assert extract_stdout_json("   ") is None

    assert extract_python_code_block("```python\nprint(1)\n```") == "print(1)\n"
    assert extract_python_code_block("```py\nprint(2)\n```") == "print(2)\n"
    assert extract_python_code_block("```json\n{}\n```") is None

    reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "a", "arguments": '{"k": 1}'}},
                        {"id": "c2", "function": {"name": "b", "arguments": "not-json"}},
                        {"id": "c3", "function": {"name": "c", "arguments": "[1, 2]"}},
                    ],
                }
            }
        ]
    }
    turn = backends.parse_chat_turn(reply)
    assert turn.content is None
    assert [(c.call_id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("c1", "a", {"k": 1}),
        ("c2", "b", {}),
        ("c3", "c", {}),
    ]


def test_arm_a_runs_purely_through_injected_ports_with_single_tool_session(tmp_path: Path) -> None:
    tool_session = _FakeToolSession()

    @contextmanager
    def open_tools():
        tool_session.opened += 1
        try:
            yield tool_session
        finally:
            tool_session.closed += 1

    final_reply = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'
    chat = _FakeChatGateway(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "feature_info", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": final_reply,
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            },
        ]
    )
    workspace = _FakeWorkspace({"type": "FeatureCollection", "features": []})
    ports = HarnessPorts(
        chat=chat,
        open_tools=open_tools,
        sandbox=_FakeSandbox(SandboxExecution(0, "", "")),
        workspace=workspace,
    )
    ollama_arm_a(_real_request(tmp_path, "A"), ports=ports)
    assert tool_session.opened == 1
    assert tool_session.closed == 1
    assert tool_session.invocations == [("feature_info", {})]
    assert workspace.deliverables == [{"relation": "touches", "de9im": "FF2F11212"}]
    assert chat.closed is False  # caller owns injected ports


def test_arm_b_runs_purely_through_injected_ports_and_cache(tmp_path: Path) -> None:
    reply = {
        "choices": [
            {"message": {"role": "assistant", "content": "```python\nprint('{\"ok\": 1}')\n```"}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }
    chat = _FakeChatGateway([reply])
    sandbox = _FakeSandbox(SandboxExecution(0, '{"ok": 1}\n', ""))
    workspace = _FakeWorkspace({"type": "FeatureCollection", "features": []})
    cache = _FakeCache()
    ports = HarnessPorts(
        chat=chat,
        open_tools=McpToolSession,
        sandbox=sandbox,
        workspace=workspace,
        cache=cache,
    )
    req1 = _real_request(tmp_path, "B", model_digest="sha256:pin")
    ollama_arm_b(req1, ports=ports)
    assert sandbox.executed == [("print('{\"ok\": 1}')\n", Path("/fake/fixture.geojson"))]
    assert workspace.deliverables == [{"ok": 1}]
    assert len(chat.calls) == 1

    # Second identical call hits the injected cache without touching chat.complete()
    req2 = _real_request(tmp_path, "B", model_digest="sha256:pin")
    ollama_arm_b(req2, ports=ports)
    assert len(chat.calls) == 1
    assert req2.cache_stats is not None and req2.cache_stats.hits == 1


def test_persistent_mcp_tool_session_reuses_single_server() -> None:
    unopened = McpToolSession()
    with pytest.raises(RuntimeError, match="not open"):
        unopened.list_tool_specs()

    with McpToolSession() as session:
        specs = session.list_tool_specs()
        names = {spec["function"]["name"] for spec in specs}
        assert {"feature_info", "relate_de9im", "jenks_breaks"} <= names
        res1 = session.call_tool("jenks_breaks", {"values": [1, 2, 10, 11], "class_count": 2})
        res2 = session.call_tool("jenks_breaks", {"values": [1, 2, 10, 11], "class_count": 2})
        assert res1 == res2
        assert len(res1["breaks"]) == 2
