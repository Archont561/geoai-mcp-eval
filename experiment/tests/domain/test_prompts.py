"""Unit tests for ``experiment.domain.prompts``."""

from __future__ import annotations

import json

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.prompts import (
    ChatTurn,
    SandboxExecution,
    ToolCall,
    extract_json_block,
    extract_python_code_block,
    extract_stdout_json,
    prompt_sha256,
)

JSON_PRIMITIVES = st.one_of(st.integers(-1000, 1000), st.booleans(), st.text(max_size=16))
JSON_DICTS = st.dictionaries(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=10),
    JSON_PRIMITIVES,
    min_size=1,
    max_size=5,
)


@given(payload=JSON_DICTS)
def test_extract_json_block_and_stdout_roundtrip_arbitrary_dicts(
    payload: dict[str, object],
) -> None:
    encoded = json.dumps(payload)
    assert extract_json_block(f"```json\n{encoded}\n```") == payload
    assert extract_stdout_json(f"log prefix\n{encoded}\n") == payload


@given(text=st.text(max_size=120))
def test_prompt_sha256_is_deterministic_64_hex_chars(text: str) -> None:
    digest = prompt_sha256(text)
    assert len(digest) == 64
    assert digest == prompt_sha256(text)


@example(code="print(1)", label="python", payload={"relation": "touches"})
@example(code="print(2)", label="py", payload={"x": 1})
@example(code="print(3)", label="", payload={"a": 1})
@given(
    code=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ()_=", min_size=1, max_size=80),
    label=st.sampled_from(["python", "py", ""]),
    payload=JSON_DICTS,
)
def test_pure_parsers_extract_stdout_and_python_blocks(
    code: str, label: str, payload: dict[str, object]
) -> None:
    encoded = json.dumps(payload)
    assert extract_json_block(f"Result: {encoded}") == payload
    assert extract_json_block("not json at all") is None
    assert extract_stdout_json(f"```json\n{encoded}\n```") == payload
    assert extract_stdout_json("not json") is None
    assert extract_python_code_block(f"```{label}\n{code}\n```") == f"{code}\n"
    assert extract_python_code_block(f"```json\n{encoded}\n```") is None


@given(
    call_id=st.text(min_size=1, max_size=16),
    name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=16),
    returncode=st.integers(min_value=-128, max_value=255),
)
def test_prompt_dto_models_roundtrip_and_validate(call_id: str, name: str, returncode: int) -> None:
    tc = ToolCall(call_id=call_id, name=name, arguments={"geometry": {}})
    turn = ChatTurn(
        content="done",
        tool_calls=(tc,),
        raw_message={"role": "assistant", "content": "done"},
    )
    assert ChatTurn.model_validate_json(turn.model_dump_json()) == turn
    sb = SandboxExecution(returncode=returncode, stdout='{"ok": true}', stderr="")
    assert SandboxExecution.model_validate_json(sb.model_dump_json()) == sb
    with pytest.raises(ValidationError):
        ToolCall(call_id=call_id, name=name, extra_key=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        sb.returncode = 1  # type: ignore[misc]
