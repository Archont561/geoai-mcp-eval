"""Unit tests for ``experiment.services.runners.ollama``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from experiment.adapters import backends
from experiment.adapters.mcp.client import McpToolSession
from experiment.domain.cache_key import CacheStats
from experiment.domain.prompts import SandboxExecution
from experiment.services import runs
from experiment.services.runners import ollama_arm_a, ollama_arm_b
from experiment.services.runners.ports import CellRequest, HarnessPorts

FINAL_JSON = '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```'


@pytest.fixture
def final_content_reply() -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": FINAL_JSON}}]}


@pytest.fixture
def feature_info_tool_reply() -> dict[str, Any]:
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
                            "function": {"name": "feature_info", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }


def test_arm_a_runs_purely_through_injected_ports_with_single_tool_session(
    sample_cell_request: CellRequest,
    fake_harness_ports: HarnessPorts,
    fake_chat_gateway: MagicMock,
    fake_tool_session: MagicMock,
    fake_cell_workspace: MagicMock,
    feature_info_tool_reply: dict[str, Any],
    final_content_reply: dict[str, Any],
) -> None:
    fake_chat_gateway.complete.side_effect = [feature_info_tool_reply, final_content_reply]
    ollama_arm_a(sample_cell_request, ports=fake_harness_ports)

    fake_tool_session.lifecycle.open.assert_called_once()
    fake_tool_session.lifecycle.close.assert_called_once()
    fake_tool_session.call_tool.assert_called_once_with("feature_info", {})
    assert fake_cell_workspace.deliverables == [{"relation": "touches", "de9im": "FF2F11212"}]
    fake_chat_gateway.close.assert_not_called()


def test_arm_b_runs_purely_through_injected_ports_and_cache(
    sample_cell_request: CellRequest,
    fake_harness_ports: HarnessPorts,
    fake_chat_gateway: MagicMock,
    fake_code_sandbox: MagicMock,
    fake_cell_workspace: MagicMock,
) -> None:
    reply = {
        "choices": [
            {"message": {"role": "assistant", "content": "```python\nprint('{\"ok\": 1}')\n```"}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }
    fake_chat_gateway.complete.return_value = reply
    fake_code_sandbox.execute.return_value = SandboxExecution(
        returncode=0, stdout='{"ok": 1}\n', stderr=""
    )

    req1 = sample_cell_request.model_copy(
        update={"arm": "B", "model_digest": "sha256:pin", "cache_stats": CacheStats()}
    )
    ollama_arm_b(req1, ports=fake_harness_ports)
    fake_code_sandbox.execute.assert_called_once_with(
        "print('{\"ok\": 1}')\n", fixture_src=fake_cell_workspace.fixture_path
    )
    assert fake_cell_workspace.deliverables == [{"ok": 1}]
    assert fake_chat_gateway.complete.call_count == 1

    req2 = req1.model_copy(update={"cache_stats": CacheStats()})
    ollama_arm_b(req2, ports=fake_harness_ports)
    assert fake_chat_gateway.complete.call_count == 1
    assert req2.cache_stats is not None and req2.cache_stats.hits == 1


def test_ollama_arm_a_tool_loop(
    monkeypatch: pytest.MonkeyPatch,
    sample_cell_request: CellRequest,
    de9im_fixture: dict[str, Any],
    final_content_reply: dict[str, Any],
) -> None:
    args = json.dumps({"geojson": de9im_fixture, "property": "ISO_A3", "equals": "POL"})
    tool_reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "feature_info", "arguments": args},
                        }
                    ],
                }
            }
        ]
    }
    fake_chat = MagicMock(side_effect=[tool_reply, final_content_reply])
    monkeypatch.setattr(backends, "chat_completions", fake_chat)

    result = runs.run_cell(sample_cell_request)
    assert result["status"] == "ok"
    assert result["oracle_passed"] is True
    assert "feature_info" in (sample_cell_request.cell / "transcript.jsonl").read_text(
        encoding="utf-8"
    )


def test_ollama_arm_a_tool_error_is_captured(
    monkeypatch: pytest.MonkeyPatch,
    sample_cell_request: CellRequest,
    final_content_reply: dict[str, Any],
) -> None:
    bad_tool_reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "no_such_tool", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(
        backends, "chat_completions", MagicMock(side_effect=[bad_tool_reply, final_content_reply])
    )
    result = runs.run_cell(sample_cell_request)
    assert result["status"] == "ok"
    assert "no_such_tool" in (sample_cell_request.cell / "transcript.jsonl").read_text(
        encoding="utf-8"
    )


def test_ollama_arm_b_executes_code_and_handles_fences(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_cell_request: CellRequest,
    final_content_reply: dict[str, Any],
) -> None:
    code = (
        "import json, os\n"
        "assert os.listdir('.') == ['input.geojson']\n"
        "fx = json.load(open('input.geojson'))\n"
        "assert fx['type'] == 'FeatureCollection'\n"
        "print(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    )
    monkeypatch.setattr(
        backends,
        "chat_completions",
        MagicMock(
            return_value={
                "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}]
            }
        ),
    )
    ok_cell = tmp_path / "ok"
    ok_cell.mkdir()
    result = runs.run_cell(sample_cell_request.model_copy(update={"arm": "B", "cell": ok_cell}))
    assert result["oracle_passed"] is True
    assert not (ok_cell / "input.geojson").exists()

    monkeypatch.setattr(
        backends,
        "chat_completions",
        MagicMock(
            return_value={
                "choices": [{"message": {"role": "assistant", "content": "no code here, sorry"}}]
            }
        ),
    )
    bad_cell = tmp_path / "bad"
    bad_cell.mkdir()
    assert (
        runs.run_cell(sample_cell_request.model_copy(update={"arm": "B", "cell": bad_cell}))[
            "oracle_passed"
        ]
        is False
    )

    monkeypatch.setattr(backends, "chat_completions", MagicMock(return_value=final_content_reply))
    jf = tmp_path / "json-fence"
    jf.mkdir()
    res_jf = runs.run_cell(sample_cell_request.model_copy(update={"arm": "B", "cell": jf}))
    assert res_jf["oracle_passed"] is False
    assert not (jf / "result.json").exists()
    transcript = (jf / "transcript.jsonl").read_text(encoding="utf-8")
    assert "no python block found" in transcript and "<string>" not in transcript

    short_code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    for label, fence in (("py", f"```py\n{short_code}```"), ("raw", f"```\n{short_code}```")):
        monkeypatch.setattr(
            backends,
            "chat_completions",
            MagicMock(
                return_value={"choices": [{"message": {"role": "assistant", "content": fence}}]}
            ),
        )
        c = tmp_path / label
        c.mkdir()
        assert (
            runs.run_cell(sample_cell_request.model_copy(update={"arm": "B", "cell": c}))[
                "oracle_passed"
            ]
            is True
        )


def test_ollama_arm_a_sums_multiturn_usage_and_aborts_on_token_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_cell_request: CellRequest,
    de9im_fixture: dict[str, Any],
    final_content_reply: dict[str, Any],
) -> None:
    args = json.dumps({"geojson": de9im_fixture, "property": "ISO_A3", "equals": "POL"})
    turn1 = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "feature_info", "arguments": args},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
    }
    turn2 = {
        **final_content_reply,
        "usage": {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
    }

    monkeypatch.setattr(backends, "chat_completions", MagicMock(side_effect=[turn1, turn2]))
    cell_ok = tmp_path / "ok"
    cell_ok.mkdir()
    res_ok = runs.run_cell(
        sample_cell_request.model_copy(
            update={"cell": cell_ok, "run_id": "r1", "max_cell_tokens": 250}
        )
    )
    assert res_ok["status"] == "ok"
    assert res_ok["usage"]["total_tokens"] == 200

    tool_mock = MagicMock(
        side_effect=AssertionError("MCP tool must not execute after token cap is exceeded")
    )
    monkeypatch.setattr(McpToolSession, "call_tool", tool_mock)
    monkeypatch.setattr(backends, "chat_completions", MagicMock(side_effect=[turn1, turn2]))
    cell_cap = tmp_path / "cap"
    cell_cap.mkdir()
    res_cap = runs.run_cell(
        sample_cell_request.model_copy(
            update={"cell": cell_cap, "run_id": "r2", "max_cell_tokens": 50}
        )
    )
    assert res_cap["status"] == "aborted"
    assert res_cap["abort_reason"] == "token_cap_exceeded"
    tool_mock.assert_not_called()
    assert res_cap["usage"]["total_tokens"] == 80
    assert res_cap["usage"]["cap_exceeded"] is True
