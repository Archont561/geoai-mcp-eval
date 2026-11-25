"""Frozen arm prompt scaffolds, chat turn value objects, and pure reply parsers.

Pure domain module: no I/O, no framework or adapter dependencies.
Prompt strings are preregistered verbatim (see ``docs/study/preregistration.md``);
never alter their bytes without a dated pre-freeze addendum.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

RESULT_JSON = "result.json"
RESULT_GEOJSON = "result.geojson"

MSG_ROLE = "role"
MSG_CONTENT = "content"

ARM_A_SYSTEM_PROMPT = (
    "You solve one GIS task with the provided tools only. Never invent data; the "
    "fixture is the only allowed input. When finished, reply with ONLY the final "
    f"deliverable as a single JSON code block ({RESULT_JSON}) or a raw GeoJSON object "
    f"({RESULT_GEOJSON}), no prose."
)

ARM_B_SYSTEM_PROMPT = (
    "You solve one GIS task by writing a Python script. Use only the standard "
    "library plus geopandas/shapely/pyproj. The fixture is available as "
    "'input.geojson' in the working directory. Reply with ONLY a single "
    "```python fenced code block containing the complete script; no prose and "
    f"no other fences. The script must print the deliverable ({RESULT_JSON} or "
    f"{RESULT_GEOJSON}) as a single JSON object to stdout and nothing else."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_PYTHON_FENCE_RE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


class ToolCall(BaseModel):
    """One model-requested tool invocation, independent of wire schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


class ChatTurn(BaseModel):
    """One assistant reply translated from the chat endpoint's wire format."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    raw_message: dict[str, Any]


class SandboxExecution(BaseModel):
    """Outcome of running one generated Python script in the Arm B sandbox."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str


def prompt_sha256(prompt: str) -> str:
    """Return the lowercase hex SHA-256 digest of a UTF-8 prompt string."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def extract_json_block(text: str) -> Any | None:
    """Extract the last valid JSON object from fenced code blocks or trailing braces."""
    candidates = _JSON_FENCE_RE.findall(text)
    if not candidates:
        brace = text.rfind("{")
        if brace == -1:
            return None
        candidates = [text[brace:]]
    for raw in reversed(candidates):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return None


def extract_stdout_json(stdout: str, *, max_tail: int = 20_000) -> Any | None:
    """Extract a JSON object from script stdout (direct parse first, then block fallback)."""
    tail = stdout[-max_tail:]
    stripped = tail.strip()
    if stripped:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return extract_json_block(tail)


def extract_python_code_block(text: str) -> str | None:
    """Return the first ``python``/``py``/untagged fenced block, or ``None``."""
    blocks = _PYTHON_FENCE_RE.findall(text)
    return blocks[0] if blocks else None
