"""Unit tests for ``experiment.services.reports``."""

from __future__ import annotations

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.reports import (
    ArchiveOverview,
    CellSummary,
    CheckView,
    CompletenessReport,
    RunSummary,
    TrialOverview,
)


@example(run_id="r1", passed=True, duration=1.2)
@given(
    run_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20),
    passed=st.booleans(),
    duration=st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
)
def test_typed_service_report_dtos_roundtrip_and_strict_validation(
    run_id: str, passed: bool, duration: float
) -> None:
    cell = CellSummary(
        task="t1",
        arm="A",
        status="ok",
        oracle_passed=passed,
        checks=(CheckView(assertion_id="c1", passed=passed, detail="ok"),),
        wall_s=duration,
    )
    summary = RunSummary(
        run_id=run_id,
        prototype=True,
        driver="scripted",
        model="scripted",
        generated_at="2026-11-25T00:00:00Z",
        cells=(cell,),
        passed=1,
        total=1,
    )
    rebuilt = RunSummary.from_mapping(summary.to_dict())
    assert rebuilt.run_id == run_id
    assert rebuilt.cells[0].checks[0].assertion_id == "c1"
    assert RunSummary.model_validate_json(summary.model_dump_json()) == summary

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

    trial = TrialOverview(
        trial_id="t1/typed_mcp/none/rep-1",
        task_id="t1",
        paradigm="typed_mcp",
        enforcement_level="none",
        repetition=1,
        task_success=True,
        predicate_score=1.0,
        silent_invalid=False,
    )
    archive = ArchiveOverview(
        run_id=run_id,
        stage="pilot",
        schema_version=1,
        model="scripted",
        model_digest=None,
        trial_count=1,
        task_success_count=1,
        task_success_rate=1.0,
        mean_predicate_score=1.0,
        has_summary=True,
        trials=(trial,),
    )
    assert ArchiveOverview.model_validate_json(archive.model_dump_json()) == archive

    with pytest.raises(ValidationError):
        CheckView(assertion_id="c1", passed=True, detail="ok", bogus=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        cell.status = "error"  # type: ignore[misc]
