"""Pure process and cost metric extraction from trial transcripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

from experiment.domain.run.measurement import CostAndProcessMetrics, TokenUsage
from experiment.domain.run.trial import TranscriptEntry


class _TranscriptTally(NamedTuple):
    assistant_turns: int
    tool_calls: int
    schema_violations: int
    repair_turns: int


def _as_dict(entry: TranscriptEntry | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(entry, TranscriptEntry):
        merged = entry.model_dump(exclude={"extra_fields"})
        merged.update(entry.extra_fields)
        return merged
    return entry


def _is_violation_entry(record: Mapping[str, Any]) -> bool:
    if record.get("error_code") or record.get("schema_violation") or record.get("is_error"):
        return True
    event = str(record.get("event") or "").lower()
    return "violation" in event or "validation_error" in event


def _is_failed_tool_entry(record: Mapping[str, Any]) -> bool:
    if _is_violation_entry(record):
        return True
    rc = record.get("returncode")
    return isinstance(rc, int) and not isinstance(rc, bool) and rc != 0


def _count_tool_calls(record: Mapping[str, Any]) -> int:
    calls = record.get("tool_calls")
    if isinstance(calls, list):
        return len(calls)
    return 1 if record.get("role") == "tool_call" else 0


def _extract_summary_usage(
    records: Sequence[Mapping[str, Any]],
) -> tuple[TokenUsage | None, int | None]:
    for record in reversed(records):
        if record.get("event") == "usage_summary" and isinstance(record.get("usage"), Mapping):
            usage_map = record["usage"]
            raw_calls = usage_map.get("llm_calls")
            llm_calls = int(raw_calls) if isinstance(raw_calls, int) else None
            return TokenUsage.from_summary_dict(usage_map), llm_calls
    return None, None


def _tally_transcript(records: Sequence[Mapping[str, Any]]) -> _TranscriptTally:
    assistant_turns = 0
    tool_calls = 0
    schema_violations = 0
    repair_turns = 0
    pending_repair = False
    for record in records:
        if record.get("role") == "assistant":
            assistant_turns += 1
            if pending_repair:
                repair_turns += 1
                pending_repair = False
        tool_calls += _count_tool_calls(record)
        if _is_violation_entry(record):
            schema_violations += 1
        if _is_failed_tool_entry(record):
            pending_repair = True
    return _TranscriptTally(assistant_turns, tool_calls, schema_violations, repair_turns)


def extract_transcript_metrics(
    entries: Sequence[TranscriptEntry | Mapping[str, Any]],
    *,
    wall_seconds: float | None = None,
    tokens: TokenUsage | None = None,
) -> CostAndProcessMetrics:
    """Extract llm_calls, tool_calls, repair_turns, schema_violations, and TokenUsage."""
    records = [_as_dict(item) for item in entries]
    tally = _tally_transcript(records)
    summary_tokens, summary_llm_calls = _extract_summary_usage(records)
    resolved_tokens = tokens if tokens is not None else (summary_tokens or TokenUsage())
    llm_calls = summary_llm_calls if summary_llm_calls is not None else tally.assistant_turns
    return CostAndProcessMetrics(
        wall_seconds=wall_seconds,
        llm_calls=llm_calls,
        tool_calls=tally.tool_calls,
        repair_turns=tally.repair_turns,
        schema_violations=tally.schema_violations,
        tokens=resolved_tokens,
    )
