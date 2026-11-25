"""Unit tests for ``experiment.services.reports``."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from experiment.services.reports import (
    ArchiveOverview,
    CellSummary,
    CheckView,
    CompletenessReport,
    RunSummary,
    TrialOverview,
)


def test_typed_service_report_dtos_roundtrip_and_strict_validation() -> None:
    cell = CellSummary(
        task="t1",
        arm="A",
        status="ok",
        oracle_passed=True,
        checks=(CheckView(assertion_id="c1", passed=True, detail="ok"),),
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
        run_id="r1",
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


def test_zero_type_ignore_in_services_package() -> None:
    services_root = Path(__file__).resolve().parents[2] / "src" / "experiment" / "services"
    hits = [
        f"{p.name}:{lineno}"
        for p in sorted(services_root.rglob("*.py"))
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "type: ignore" in line
    ]
    assert hits == [], f"Unexpected type: ignore in services/: {hits}"
