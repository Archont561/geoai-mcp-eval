"""Pure token usage accounting and per-trial budget enforcement.

Zero I/O and zero framework imports. Token counts come strictly from endpoint
responses; missing values stay ``None`` with an explicit warning and are never
estimated client-side.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from experiment.domain.run.measurement import TokenUsage

WARNING_MISSING_USAGE = "endpoint did not report token usage"
WARNING_PARTIAL_USAGE = "endpoint reported partial token usage"
WARNING_NO_LLM_CALLS = "no LLM completions recorded"
ABORT_REASON_TOKEN_CAP = "token_cap_exceeded"


class TokenCapExceededError(Exception):
    """Raised when reported trial token usage exceeds the trial budget."""

    def __init__(self, tokens_used: int, max_cell_tokens: int) -> None:
        self.tokens_used = tokens_used
        self.max_cell_tokens = max_cell_tokens
        self.reason = ABORT_REASON_TOKEN_CAP
        super().__init__(
            f"{ABORT_REASON_TOKEN_CAP}: trial used {tokens_used} tokens (cap: {max_cell_tokens})"
        )


def _valid_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _first_valid_int(raw: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _valid_int(raw.get(key))
        if value is not None:
            return value
    return None


class UsageSnapshot(BaseModel):
    """Reported token counts for a single LLM completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    warning: str | None = None

    @property
    def is_complete(self) -> bool:
        return (
            self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens is not None
        )

    def to_transcript_usage(self) -> dict[str, int | None] | None:
        if self.input_tokens is None and self.output_tokens is None and self.total_tokens is None:
            return None
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


def extract_response_usage(reply: Mapping[str, Any]) -> UsageSnapshot:
    """Read reported usage from an OpenAI-compatible response without estimating."""
    raw = reply.get("usage")
    if not isinstance(raw, Mapping):
        return UsageSnapshot(
            input_tokens=None, output_tokens=None, total_tokens=None, warning=WARNING_MISSING_USAGE
        )

    inp = _first_valid_int(raw, "prompt_tokens", "input_tokens")
    out = _first_valid_int(raw, "completion_tokens", "output_tokens")
    total = _valid_int(raw.get("total_tokens"))
    if inp is None and out is None and total is None:
        return UsageSnapshot(
            input_tokens=None, output_tokens=None, total_tokens=None, warning=WARNING_MISSING_USAGE
        )
    if total is None and inp is not None and out is not None:
        total = inp + out
    warning = WARNING_PARTIAL_USAGE if None in (inp, out, total) else None
    return UsageSnapshot(input_tokens=inp, output_tokens=out, total_tokens=total, warning=warning)


class UsageAccumulator(BaseModel):
    """Accumulates reported token usage across all completions in one trial."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    max_cell_tokens: int | None = Field(default=None, ge=1)
    llm_calls: int = 0
    calls_with_usage: int = 0
    calls_missing_usage: int = 0
    cap_exceeded: bool = False
    warnings: list[str] = Field(default_factory=list)
    _input_sum: int = PrivateAttr(default=0)
    _output_sum: int = PrivateAttr(default=0)
    _total_sum: int = PrivateAttr(default=0)
    _input_complete: bool = PrivateAttr(default=True)
    _output_complete: bool = PrivateAttr(default=True)
    _total_complete: bool = PrivateAttr(default=True)
    _observed_total: int = PrivateAttr(default=0)

    def _add_warning(self, message: str | None) -> None:
        if message and message not in self.warnings:
            self.warnings.append(message)

    def _accumulate_counts(self, snapshot: UsageSnapshot) -> None:
        if snapshot.input_tokens is not None:
            self._input_sum += snapshot.input_tokens
        else:
            self._input_complete = False
        if snapshot.output_tokens is not None:
            self._output_sum += snapshot.output_tokens
        else:
            self._output_complete = False
        if snapshot.total_tokens is not None:
            self._total_sum += snapshot.total_tokens
            self._observed_total += snapshot.total_tokens
        else:
            self._total_complete = False
            self._observed_total += (snapshot.input_tokens or 0) + (snapshot.output_tokens or 0)

    def record(self, snapshot: UsageSnapshot) -> None:
        """Record one completion's reported usage and evaluate the token cap."""
        self.llm_calls += 1
        if snapshot.is_complete:
            self.calls_with_usage += 1
        else:
            self.calls_missing_usage += 1
        self._add_warning(snapshot.warning)
        self._accumulate_counts(snapshot)
        if self.max_cell_tokens is not None and self._observed_total > self.max_cell_tokens:
            self.cap_exceeded = True

    @property
    def observed_total_tokens(self) -> int:
        return self._observed_total

    def to_token_usage(self) -> TokenUsage:
        """Return a validated TokenUsage DTO without imputing missing values."""
        return TokenUsage.from_summary_dict(self.to_summary())

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-safe per-trial usage summary without imputing missing values."""
        if self.llm_calls == 0:
            warnings = list(self.warnings)
            if WARNING_NO_LLM_CALLS not in warnings:
                warnings.append(WARNING_NO_LLM_CALLS)
            return {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "llm_calls": 0,
                "calls_with_usage": 0,
                "calls_missing_usage": 0,
                "max_cell_tokens": self.max_cell_tokens,
                "cap_exceeded": False,
                "warnings": warnings,
            }
        return {
            "input_tokens": self._input_sum if self._input_complete else None,
            "output_tokens": self._output_sum if self._output_complete else None,
            "total_tokens": self._total_sum if self._total_complete else None,
            "llm_calls": self.llm_calls,
            "calls_with_usage": self.calls_with_usage,
            "calls_missing_usage": self.calls_missing_usage,
            "max_cell_tokens": self.max_cell_tokens,
            "cap_exceeded": self.cap_exceeded,
            "warnings": list(self.warnings),
        }


def _sum_complete_field(cell_usages: Sequence[Mapping[str, Any]], key: str) -> int | None:
    if not cell_usages:
        return None
    total = 0
    for cell in cell_usages:
        value = _valid_int(cell.get(key))
        if value is None:
            return None
        total += value
    return total


def _collect_warnings(cell_usages: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for cell in cell_usages:
        for warn in cell.get("warnings") or ():
            if warn and str(warn) not in warnings:
                warnings.append(str(warn))
    return warnings


def _is_complete_cell(cell: Mapping[str, Any]) -> bool:
    return all(
        _valid_int(cell.get(k)) is not None
        for k in ("input_tokens", "output_tokens", "total_tokens")
    )


def _is_missing_usage_cell(cell: Mapping[str, Any]) -> bool:
    return not _is_complete_cell(cell) and int(cell.get("llm_calls") or 0) > 0


def aggregate_run_usage(cell_usages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sum token counts across trials; keep a total ``None`` if any trial lacks it."""
    llm_calls = sum(int(cell.get("llm_calls") or 0) for cell in cell_usages)
    cells_with_usage = sum(1 for cell in cell_usages if _is_complete_cell(cell))
    cells_missing_usage = sum(1 for cell in cell_usages if _is_missing_usage_cell(cell))
    return {
        "input_tokens": _sum_complete_field(cell_usages, "input_tokens"),
        "output_tokens": _sum_complete_field(cell_usages, "output_tokens"),
        "total_tokens": _sum_complete_field(cell_usages, "total_tokens"),
        "llm_calls": llm_calls,
        "cells_with_usage": cells_with_usage,
        "cells_missing_usage": cells_missing_usage,
        "warnings": _collect_warnings(cell_usages),
    }
