"""Unit tests for ``experiment.domain.run._common``."""

from __future__ import annotations

import pytest

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


def test_parse_enforcement_level_accepts_names_and_legacy_codes() -> None:
    for level in ENFORCEMENT_LEVELS:
        assert parse_enforcement_level(level) == level
        assert parse_enforcement_level(f"  {level.upper()}  ") == level
    assert parse_enforcement_level("N0") == "none"
    assert parse_enforcement_level("n3") == "semantic_repair"
    with pytest.raises(ValueError):
        parse_enforcement_level("N9")


def test_parse_execution_status_normalizes_mock_smoke_and_fallback() -> None:
    assert parse_execution_status("ok") == "ok"
    assert parse_execution_status("ABORTED") == "aborted"
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
