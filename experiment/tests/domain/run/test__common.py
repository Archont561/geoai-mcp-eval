"""Unit tests for ``experiment.domain.run._common``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from experiment.domain.run import (
    ENFORCEMENT_LEVELS,
    arm_to_paradigm,
    enforce_code_to_level,
    infer_assertion_tier,
    parse_enforcement_level,
    parse_execution_status,
)


def test_legacy_mappers_translate_arms_and_enforcement_levels() -> None:
    assert arm_to_paradigm("A") == "typed_mcp"
    assert arm_to_paradigm("B") == "codegen"
    assert arm_to_paradigm("C") == "hybrid_mcp_code"
    assert arm_to_paradigm("D") == "code_driving_mcp"
    assert arm_to_paradigm("H") == "human_gui"
    assert enforce_code_to_level("N0") == "none"
    assert enforce_code_to_level("N1") == "declarative"
    assert enforce_code_to_level("N2") == "syntactic"
    assert enforce_code_to_level("N3") == "semantic_repair"
    assert enforce_code_to_level("N4") == "transactional"
    with pytest.raises(ValueError, match="unknown arm"):
        arm_to_paradigm("Z")
    with pytest.raises(ValueError, match="unknown enforcement"):
        enforce_code_to_level("N9")


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


def test_parse_enforcement_level_accepts_legacy_codes_and_rejects_unknown() -> None:
    assert parse_enforcement_level("N0") == "none"
    assert parse_enforcement_level("n3") == "semantic_repair"
    with pytest.raises(ValueError):
        parse_enforcement_level("N9")


@given(status=st.sampled_from(["ok", "error", "aborted", "smoke"]))
def test_parse_execution_status_is_case_insensitive_for_valid_statuses(status: str) -> None:
    assert parse_execution_status(status) == status
    assert parse_execution_status(status.upper()) == status


def test_parse_execution_status_normalizes_mock_smoke_and_fallback() -> None:
    assert parse_execution_status("mock-smoke") == "smoke"
    assert parse_execution_status("unknown-status") == "ok"
    assert parse_execution_status(None, default="error") == "error"


def test_infer_assertion_tier_maps_legacy_letters_and_types() -> None:
    assert infer_assertion_tier("geojson_feature_count") == "trivial"
    assert infer_assertion_tier("representative_point_matches") == "spatial"
    assert infer_assertion_tier("de9im_relation") == "spatial"
    assert infer_assertion_tier("jenks_classification") == "value"
    assert infer_assertion_tier("custom_type", explicit_tier="A") == "trivial"
    assert infer_assertion_tier("custom_type", explicit_tier="B") == "spatial"
    assert infer_assertion_tier("custom_type", explicit_tier="C") == "value"
    assert infer_assertion_tier("custom_type", explicit_tier="spatial") == "spatial"
    assert infer_assertion_tier("unknown_type") is None
