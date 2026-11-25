"""Unit tests for ``experiment.domain.prompts``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.prompts import (
    ARM_A_SYSTEM_PROMPT,
    ARM_B_SYSTEM_PROMPT,
    ChatTurn,
    SandboxExecution,
    ToolCall,
    extract_json_block,
    extract_python_code_block,
    extract_stdout_json,
    prompt_sha256,
)

RATIFIED_ARM_B_SHA256 = "5c44378126c5b889a159b7524ea83bf0d365f45854ee2559b38230851ac1c985"


def test_ratified_prompt_scaffolds_are_preserved_verbatim() -> None:
    assert prompt_sha256(ARM_B_SYSTEM_PROMPT) == RATIFIED_ARM_B_SHA256
    assert len(ARM_B_SYSTEM_PROMPT.encode("utf-8")) == 418
    assert "provided tools only" in ARM_A_SYSTEM_PROMPT
    assert len(prompt_sha256(ARM_A_SYSTEM_PROMPT)) == 64


def test_extract_json_block() -> None:
    assert extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_block('Result: {"relation": "touches"}') == {"relation": "touches"}
    assert extract_json_block("not json at all") is None


def test_pure_parsers_extract_stdout_and_python_blocks() -> None:
    assert extract_stdout_json('{"relation": "touches"}\n') == {"relation": "touches"}
    assert extract_stdout_json('warning line\n{"ok": true}') == {"ok": True}
    assert extract_stdout_json('```json\n{"x": 1}\n```') == {"x": 1}
    assert extract_stdout_json("not json") is None

    assert extract_python_code_block("```python\nprint(1)\n```") == "print(1)\n"
    assert extract_python_code_block("```py\nprint(2)\n```") == "print(2)\n"
    assert extract_python_code_block('```json\n{"a": 1}\n```') is None
    assert extract_python_code_block("```\nprint(3)\n```") == "print(3)\n"


def test_prompt_dto_models_roundtrip_and_validate() -> None:
    tc = ToolCall(call_id="call-1", name="area", arguments={"geometry": {}})
    turn = ChatTurn(
        content="done",
        tool_calls=(tc,),
        raw_message={"role": "assistant", "content": "done"},
    )
    assert ChatTurn.model_validate_json(turn.model_dump_json()) == turn
    sb = SandboxExecution(returncode=0, stdout='{"ok": true}', stderr="")
    assert SandboxExecution.model_validate_json(sb.model_dump_json()) == sb
    with pytest.raises(ValidationError):
        ToolCall(call_id="c1", name="area", extra_key=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        sb.returncode = 1  # type: ignore[misc]
