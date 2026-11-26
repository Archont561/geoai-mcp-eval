"""Unit tests for ``experiment.domain.run.trial``."""

from __future__ import annotations

import pytest
from hypothesis import example, given
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


@given(
    paradigm=st.sampled_from(["codegen", "human_gui"]),
    level=st.sampled_from(["declarative", "syntactic", "semantic_repair", "transactional"]),
)
def test_treatment_rejects_enforcement_on_codegen_and_human_gui(paradigm: str, level: str) -> None:
    Treatment.model_validate({"paradigm": paradigm, "enforcement_level": "none"})
    with pytest.raises(ValidationError, match="enforcement_level must be 'none'"):
        Treatment.model_validate({"paradigm": paradigm, "enforcement_level": level})


@example(task_id="analysis-de9im-001", repetition=1, bad_path="/etc/passwd")
@example(task_id="analysis-de9im-001", repetition=1, bad_path="../escape.json")
@example(task_id="analysis-de9im-001", repetition=1, bad_path="a/../../b")
@example(task_id="analysis-de9im-001", repetition=1, bad_path="dir\\file.json")
@given(
    task_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=24),
    repetition=st.integers(min_value=1, max_value=100),
    bad_path=st.one_of(
        st.just("/etc/passwd"),
        st.just("../escape.json"),
        st.just("a/../../b"),
        st.just("dir\\file.json"),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20).map(
            lambda part: f"../{part}"
        ),
    ),
)
def test_trial_record_validates_key_matches_treatment_and_safe_artifact_paths(
    task_id: str, repetition: int, bad_path: str
) -> None:
    key = TrialKey(
        task_id=task_id,
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        repetition=repetition,
    )
    Treatment(paradigm="typed_mcp", enforcement_level="semantic_repair")
    mismatch = Treatment(paradigm="codegen", enforcement_level="none")
    with pytest.raises(ValidationError, match="key and treatment must agree"):
        TrialRecord(key=key, treatment=mismatch, driver="ollama", status="ok")
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
