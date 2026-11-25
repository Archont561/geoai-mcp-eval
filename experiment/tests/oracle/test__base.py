"""Unit tests for ``experiment.oracle._base``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiment.oracle._base import (
    AssertionResult,
    DeterminismReport,
    OracleVerdict,
    geojson_features,
    read_json,
    safe_path,
)


def test_oracle_models_to_dict_and_pydantic_validation() -> None:
    check = AssertionResult(assertion_id="c1", passed=True, message="ok")
    verdict = OracleVerdict(passed=True, checks=(check,))
    assert verdict.to_dict() == {
        "passed": True,
        "checks": [{"assertion_id": "c1", "passed": True, "message": "ok"}],
    }
    assert OracleVerdict.model_validate_json(verdict.model_dump_json()) == verdict

    report = DeterminismReport(
        passed=True,
        required_runs=3,
        consistent=True,
        run_results=(verdict.to_dict(),),
        issues=(),
    )
    assert DeterminismReport.model_validate_json(report.model_dump_json()) == report

    with pytest.raises(ValidationError):
        AssertionResult(assertion_id="c1", passed=True, message="ok", bogus=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        DeterminismReport(
            passed=False, required_runs=-1, consistent=False, run_results=(), issues=()
        )


def test_safe_path_read_json_and_geojson_features(tmp_path: Path) -> None:
    target = tmp_path / "data.geojson"
    target.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    assert safe_path(tmp_path, "data.geojson") == target.resolve()
    assert read_json(target) == {"type": "FeatureCollection", "features": []}
    assert geojson_features(target) == []

    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps({"type": "Feature", "features": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        safe_path(tmp_path, "../outside.json")
    with pytest.raises(ValueError, match="FeatureCollection"):
        geojson_features(bad)
