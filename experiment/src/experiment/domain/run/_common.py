"""Shared strict Pydantic configuration and English experiment ontology vocabularies."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

STRICT_MODEL = ConfigDict(extra="forbid", frozen=True)

RunStage = Literal["preflight", "smoke", "pilot", "study"]
Paradigm = Literal[
    "typed_mcp",
    "codegen",
    "hybrid_mcp_code",
    "code_driving_mcp",
    "human_gui",
]
EnforcementLevel = Literal[
    "none",
    "declarative",
    "syntactic",
    "semantic_repair",
    "transactional",
]
ExecutionStatus = Literal["ok", "aborted", "error", "smoke"]
AssertionTier = Literal["trivial", "spatial", "value"]
ArtifactKind = Literal["deliverable", "transcript", "log", "oracle_passes", "script", "other"]
TrajectoryClass = Literal["typed_only", "code_only", "mixed"]
FailureClass = Literal[
    "interface_adjacent",
    "workflow_silent",
    "hallucinated_structure",
    "other",
]

_ARM_TO_PARADIGM: dict[str, Paradigm] = {
    "A": "typed_mcp",
    "B": "codegen",
    "C": "hybrid_mcp_code",
    "D": "code_driving_mcp",
    "H": "human_gui",
}
_ENFORCE_TO_LEVEL: dict[str, EnforcementLevel] = {
    "N0": "none",
    "N1": "declarative",
    "N2": "syntactic",
    "N3": "semantic_repair",
    "N4": "transactional",
}
ENFORCEMENT_LEVELS: tuple[EnforcementLevel, ...] = (
    "none",
    "declarative",
    "syntactic",
    "semantic_repair",
    "transactional",
)
_ENFORCEMENT_BY_NAME: dict[str, EnforcementLevel] = {lvl: lvl for lvl in ENFORCEMENT_LEVELS}
_EXECUTION_STATUS_BY_NAME: dict[str, ExecutionStatus] = {
    "ok": "ok",
    "aborted": "aborted",
    "error": "error",
    "smoke": "smoke",
    "mock-smoke": "smoke",
}


def arm_to_paradigm(arm: str) -> Paradigm:
    """Translate a legacy arm letter (A/B/C/D/H) into its English paradigm name."""
    key = arm.strip().upper()
    if key not in _ARM_TO_PARADIGM:
        raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(_ARM_TO_PARADIGM)}")
    return _ARM_TO_PARADIGM[key]


def enforce_code_to_level(code: str) -> EnforcementLevel:
    """Translate a legacy enforcement code (N0..N4) into its English level name."""
    key = code.strip().upper()
    if key not in _ENFORCE_TO_LEVEL:
        raise ValueError(
            f"unknown enforcement code {code!r}; expected one of {sorted(_ENFORCE_TO_LEVEL)}"
        )
    return _ENFORCE_TO_LEVEL[key]


def parse_enforcement_level(raw: str) -> EnforcementLevel:
    """Parse an English enforcement level name or legacy N0..N4 code."""
    cleaned = raw.strip()
    by_name = _ENFORCEMENT_BY_NAME.get(cleaned.lower())
    if by_name is not None:
        return by_name
    return enforce_code_to_level(cleaned)


def parse_execution_status(raw: object, *, default: ExecutionStatus = "ok") -> ExecutionStatus:
    """Normalize a raw status token (including ``mock-smoke``) to :data:`ExecutionStatus`."""
    if isinstance(raw, str):
        found = _EXECUTION_STATUS_BY_NAME.get(raw.strip().lower())
        if found is not None:
            return found
    return default
