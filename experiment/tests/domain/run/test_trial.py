"""Unit tests for ``experiment.domain.run.trial``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.run.trial import (
    ArtifactRef,
    TranscriptEntry,
    Treatment,
    TrialKey,
    TrialRecord,
)

VALID_SHA = "a" * 64


def test_treatment_rejects_enforcement_on_codegen_and_human_gui() -> None:
    Treatment(paradigm="codegen", enforcement_level="none")
    Treatment(paradigm="human_gui", enforcement_level="none")
    Treatment(paradigm="typed_mcp", enforcement_level="semantic_repair")

    with pytest.raises(ValidationError, match="enforcement_level must be 'none'"):
        Treatment(paradigm="codegen", enforcement_level="syntactic")
    with pytest.raises(ValidationError, match="enforcement_level must be 'none'"):
        Treatment(paradigm="human_gui", enforcement_level="declarative")


def test_trial_record_validates_key_matches_treatment_and_safe_artifact_paths() -> None:
    key = TrialKey(
        task_id="analysis-de9im-001",
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        repetition=1,
    )
    mismatch = Treatment(paradigm="codegen", enforcement_level="none")
    with pytest.raises(ValidationError, match="key and treatment must agree"):
        TrialRecord(key=key, treatment=mismatch, driver="ollama", status="ok")

    for bad_path in ("/etc/passwd", "../escape.json", "a/../../b", "dir\\file.json"):
        with pytest.raises(ValidationError, match="relative POSIX path"):
            ArtifactRef(path=bad_path, sha256=VALID_SHA, bytes=10)


def test_transcript_entry_roundtrip() -> None:
    entry = TranscriptEntry(role="assistant", content="done", cache_hit=False)
    assert entry.role == "assistant"
    assert TranscriptEntry.model_validate_json(entry.model_dump_json()) == entry
