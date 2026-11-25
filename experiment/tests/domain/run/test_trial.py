"""Unit tests for ``experiment.domain.run.trial``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run.trial import (
    ArtifactRef,
    TranscriptEntry,
    Treatment,
    TrialKey,
    TrialRecord,
)

VALID_SHA = "a" * 64


@given(
    task_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=24),
    repetition=st.integers(min_value=1, max_value=100),
    enforcement=st.sampled_from(
        ["none", "declarative", "syntactic", "semantic_repair", "transactional"]
    ),
)
def test_trial_key_slug_and_treatment_roundtrip(
    task_id: str, repetition: int, enforcement: str
) -> None:
    key = TrialKey(
        task_id=task_id,
        paradigm="typed_mcp",
        enforcement_level=enforcement,  # type: ignore[arg-type]
        repetition=repetition,
    )
    assert key.slug == f"{task_id}/typed_mcp/{enforcement}/rep-{repetition}"
    assert TrialKey.model_validate_json(key.model_dump_json()) == key


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


@given(
    role=st.sampled_from(["meta", "system", "user", "assistant", "tool", "harness"]),
    content=st.text(max_size=60),
    cache_hit=st.booleans(),
)
def test_transcript_entry_roundtrip(role: str, content: str, cache_hit: bool) -> None:
    entry = TranscriptEntry(role=role, content=content, cache_hit=cache_hit)
    assert entry.role == role
    assert TranscriptEntry.model_validate_json(entry.model_dump_json()) == entry
