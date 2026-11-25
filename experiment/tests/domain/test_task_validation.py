"""Unit tests for ``experiment.domain.task_validation``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.task_validation import (
    ValidationIssue,
    ValidationReport,
    extract_fixture_paths,
    validate_assertion_semantics,
    validate_fixture_document,
    validate_suite_coverage,
)


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


@given(
    task_count=st.integers(min_value=0, max_value=50),
    messages=st.lists(st.text(min_size=1, max_size=30), max_size=5),
)
def test_validation_report_passed_iff_no_issues_and_roundtrips(
    task_count: int, messages: list[str]
) -> None:
    issues = tuple(ValidationIssue(path="tasks/a.yaml", message=msg) for msg in messages)
    report = ValidationReport(
        task_count=task_count,
        traps_found=frozenset({"crs-axis-order"}),
        issues=issues,
    )
    assert report.passed is (len(issues) == 0)
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def test_validation_issue_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ValidationIssue(path="x", message="y", extra=1)  # type: ignore[call-arg]
