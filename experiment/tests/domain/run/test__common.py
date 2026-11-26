"""Unit tests for ``experiment.domain.run._common``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from experiment.domain.run import (
    ENFORCEMENT_LEVELS,
    Arm,
    ArtifactKind,
    AssertionTier,
    Driver,
    EnforcementLevel,
    FailureClass,
    Paradigm,
    RunStage,
    TrajectoryClass,
    arm_to_paradigm,
    enforce_code_to_level,
    infer_assertion_tier,
    parse_enforcement_level,
    parse_execution_status,
)


@given(
    pair=st.sampled_from(
        [
            ("A", "typed_mcp"),
            ("B", "codegen"),
            ("C", "hybrid_mcp_code"),
            ("D", "code_driving_mcp"),
            ("H", "human_gui"),
        ]
    ),
    lowercase=st.booleans(),
)
def test_legacy_arm_mappings(pair: tuple[str, str], lowercase: bool) -> None:
    arm, expected = pair
    assert arm_to_paradigm(arm.lower() if lowercase else arm) == expected


@given(
    pair=st.sampled_from(
        [
            ("N0", "none"),
            ("N1", "declarative"),
            ("N2", "syntactic"),
            ("N3", "semantic_repair"),
            ("N4", "transactional"),
        ]
    ),
    lowercase=st.booleans(),
)
def test_legacy_enforcement_mappings(pair: tuple[str, str], lowercase: bool) -> None:
    code, expected = pair
    token = code.lower() if lowercase else code
    assert enforce_code_to_level(token) == expected
    assert parse_enforcement_level(token) == expected


@given(unknown=st.text(alphabet="efgijklmopqrstuvwxyz", min_size=1, max_size=8))
def test_legacy_arm_rejects_unknown_codes(unknown: str) -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        arm_to_paradigm(unknown)


@given(index=st.integers(min_value=5, max_value=9999))
def test_enforcement_rejects_unknown_codes(index: int) -> None:
    with pytest.raises(ValueError, match="unknown enforcement"):
        enforce_code_to_level(f"N{index}")
    with pytest.raises(ValueError):
        parse_enforcement_level(f"N{index}")


@given(
    level=st.sampled_from(ENFORCEMENT_LEVELS),
    pad_left=st.integers(min_value=0, max_value=3),
    pad_right=st.integers(min_value=0, max_value=3),
    upper=st.booleans(),
)
def test_parse_enforcement_level_normalizes_whitespace_and_case(
    level: str, pad_left: int, pad_right: int, upper: bool
) -> None:
    raw = " " * pad_left + (level.upper() if upper else level) + " " * pad_right
    assert parse_enforcement_level(raw) == level


@given(status=st.sampled_from(["ok", "error", "aborted", "smoke"]))
def test_parse_execution_status_is_case_insensitive_for_valid_statuses(status: str) -> None:
    assert parse_execution_status(status) == status
    assert parse_execution_status(status.upper()) == status


@given(
    fallback=st.sampled_from(["ok", "error", "aborted", "smoke"]),
    unknown=st.text(alphabet="xyz-", min_size=1, max_size=12),
)
def test_status_alias_and_fallback(fallback: str, unknown: str) -> None:
    assert parse_execution_status("mock-smoke", default=fallback) == "smoke"
    assert parse_execution_status("unknown-status") == "ok"
    assert parse_execution_status(unknown, default=fallback) == fallback
    assert parse_execution_status(None, default=fallback) == fallback


@given(
    pair=st.sampled_from(
        [
            ("geojson_feature_count", None, "trivial"),
            ("representative_point_matches", None, "spatial"),
            ("de9im_relation", None, "spatial"),
            ("jenks_classification", None, "value"),
            ("custom_type", "A", "trivial"),
            ("custom_type", "B", "spatial"),
            ("custom_type", "C", "value"),
            ("custom_type", "spatial", "spatial"),
            ("unknown_type", None, None),
        ]
    )
)
def test_assertion_tier_maps_known_types_and_legacy_aliases(
    pair: tuple[str, str | None, str | None],
) -> None:
    assertion_type, explicit_tier, expected = pair
    assert infer_assertion_tier(assertion_type, explicit_tier=explicit_tier) == expected


@given(level=st.sampled_from(list(EnforcementLevel)))
def test_enforcement_level_legacy_code_roundtrips(level: EnforcementLevel) -> None:
    code = level.legacy_code()
    assert EnforcementLevel.from_code(code) is level
    assert EnforcementLevel.parse(code.lower()) is level


@given(arm=st.sampled_from(list(Arm)))
def test_arm_expand_and_to_paradigm_are_consistent(arm: Arm) -> None:
    assert Arm.expand(arm.value.lower()) == (arm,)
    assert Arm.expand("both") == (Arm.A, Arm.B)
    assert arm.to_paradigm() is Paradigm.from_arm(arm)


@given(
    driver=st.sampled_from(list(Driver)),
    model=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789:-.", min_size=1, max_size=24),
)
def test_driver_parse_and_model_label(driver: Driver, model: str) -> None:
    assert Driver.parse(f" {driver.value.upper()} ") is driver
    expected = model if driver is Driver.OLLAMA else "scripted-canned"
    assert driver.model_label(model) == expected
    with pytest.raises(ValueError, match="--driver"):
        Driver.parse("unsupported-driver")


@given(paradigm=st.sampled_from(list(Paradigm)))
def test_paradigm_allows_enforcement_excludes_codegen_and_human(paradigm: Paradigm) -> None:
    expected = paradigm not in (Paradigm.CODEGEN, Paradigm.HUMAN_GUI)
    assert paradigm.allows_enforcement() is expected


@given(
    stem=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=16),
    ext=st.sampled_from([".gpkg", ".log", ".py", ".bin"]),
)
def test_artifact_kind_from_filename_classifies_known_and_unknown_suffixes(
    stem: str, ext: str
) -> None:
    kind = ArtifactKind.from_filename(f"nested/{stem}{ext}")
    expected = {
        ".gpkg": ArtifactKind.DELIVERABLE,
        ".log": ArtifactKind.LOG,
        ".py": ArtifactKind.SCRIPT,
        ".bin": ArtifactKind.OTHER,
    }[ext]
    assert kind is expected
    assert ArtifactKind.from_filename("oracle-passes.json") is ArtifactKind.ORACLE_PASSES
    assert ArtifactKind.from_filename("transcript.jsonl") is ArtifactKind.TRANSCRIPT


@given(
    enum_cls=st.sampled_from([RunStage, TrajectoryClass, FailureClass, AssertionTier]),
)
def test_run_str_enums_roundtrip_by_value(enum_cls: type[RunStage]) -> None:
    for member in enum_cls:
        assert enum_cls(member.value) is member
        assert str(member) == member.value
