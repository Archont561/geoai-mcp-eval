"""Unit tests for pure domain validation rules, enforcement parsers, and typed service DTOs."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiment.domain.run import (
    ENFORCEMENT_LEVELS,
    parse_enforcement_level,
    parse_execution_status,
)
from experiment.domain.task_validation import (
    extract_fixture_paths,
    validate_assertion_semantics,
    validate_fixture_document,
    validate_suite_coverage,
)
from experiment.services.reports import CellSummary, CheckView, CompletenessReport, RunSummary


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


def test_domain_task_validation_pure_helpers() -> None:
    bad_fc = validate_fixture_document("t1", "f.geojson", {"type": "Point"})
    assert bad_fc is not None and "FeatureCollection" in bad_fc.message
    dup_id = validate_fixture_document(
        "t1",
        "f.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {"properties": {"ISO_A3": "POL"}},
                {"properties": {"ISO_A3": "POL"}},
            ],
        },
    )
    assert dup_id is not None and "ISO_A3" in dup_id.message
    assert (
        validate_fixture_document(
            "t1",
            "f.geojson",
            {"type": "FeatureCollection", "features": [{"properties": {"ISO_A3": "POL"}}]},
        )
        is None
    )

    unknown = validate_assertion_semantics("t1", {"id": "a1", "type": "bogus"})
    assert len(unknown) == 1 and "unimplemented" in unknown[0].message
    bad_rel = validate_assertion_semantics(
        "t1",
        {
            "id": "a2",
            "type": "de9im_relation",
            "fixture": "f.geojson",
            "output": "out.json",
            "id_field": "ISO_A3",
            "left_id": "A",
            "right_id": "B",
            "expected_relation": "crosses",
            "expected_matrix": "FF2F11212",
        },
    )
    assert any("unsupported relation" in i.message for i in bad_rel)
    assert extract_fixture_paths(
        {"fixtures": {"input": "a.geojson"}},
        [{"fixture": "b.geojson"}, "ignored"],
    ) == ["a.geojson", "b.geojson"]

    traps, issues = validate_suite_coverage(
        [
            ("a.yaml", {"id": "t1", "family": "P", "required_traps": ["crs-axis-order"]}),
            ("b.yaml", {"id": "t1", "family": "P", "required_traps": []}),
        ],
        "suite",
    )
    assert traps == frozenset({"crs-axis-order"})
    assert any("duplicate task ID" in i.message for i in issues)
    assert any("missing task family A" in i.message for i in issues)
    assert any("required pilot trap" in i.message for i in issues)


def test_typed_service_report_dtos_roundtrip() -> None:
    cell = CellSummary(
        task="t1",
        arm="A",
        status="ok",
        oracle_passed=True,
        checks=(CheckView("c1", True, "ok"),),
        wall_s=1.2,
    )
    summary = RunSummary(
        run_id="r1",
        prototype=True,
        driver="scripted",
        model="scripted",
        generated_at="2026-11-25T00:00:00Z",
        cells=(cell,),
        passed=1,
        total=1,
    )
    rebuilt = RunSummary.from_mapping(summary.to_dict())
    assert rebuilt.run_id == "r1"
    assert rebuilt.cells[0].checks[0].assertion_id == "c1"

    assert CompletenessReport.from_mapping({}) is None
    comp = CompletenessReport.from_mapping(
        {
            "expected_cells": ["t1/A/rep-1"],
            "logged_cells": ["t1/A/rep-1"],
            "missing": [],
            "oracle": {"t1/A/rep-1": "pass"},
            "complete": True,
        }
    )
    assert comp is not None
    assert comp.complete is True
    assert comp.oracle_rows == (("t1/A/rep-1", "pass"),)


def test_zero_type_ignore_in_services_package() -> None:
    services_root = Path(__file__).resolve().parents[1] / "src" / "experiment" / "services"
    hits = [
        f"{p.name}:{lineno}"
        for p in sorted(services_root.rglob("*.py"))
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "type: ignore" in line
    ]
    assert hits == [], f"Unexpected type: ignore in services/: {hits}"
