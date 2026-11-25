"""Unit tests for ``experiment.oracle._base``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.oracle._base import (
    AssertionResult,
    DeterminismReport,
    OracleVerdict,
    geojson_features,
    read_json,
    safe_path,
)

PATH_SEG = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=10)


@given(
    assertion_id=st.text(min_size=1, max_size=24),
    passed=st.booleans(),
    message=st.text(max_size=60),
    required_runs=st.integers(min_value=0, max_value=10),
)
def test_oracle_models_to_dict_and_roundtrip_for_arbitrary_verdicts(
    assertion_id: str, passed: bool, message: str, required_runs: int
) -> None:
    check = AssertionResult(assertion_id=assertion_id, passed=passed, message=message)
    verdict = OracleVerdict(passed=passed, checks=(check,))
    assert verdict.to_dict() == {
        "passed": passed,
        "checks": [{"assertion_id": assertion_id, "passed": passed, "message": message}],
    }
    assert OracleVerdict.model_validate_json(verdict.model_dump_json()) == verdict

    report = DeterminismReport(
        passed=passed,
        required_runs=required_runs,
        consistent=passed,
        run_results=(verdict.to_dict(),),
        issues=(),
    )
    assert DeterminismReport.model_validate_json(report.model_dump_json()) == report


def test_oracle_models_reject_extra_fields_and_negative_runs() -> None:
    with pytest.raises(ValidationError):
        AssertionResult(assertion_id="c1", passed=True, message="ok", bogus=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        DeterminismReport(
            passed=False, required_runs=-1, consistent=False, run_results=(), issues=()
        )


@given(segments=st.lists(PATH_SEG, min_size=1, max_size=4))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_safe_path_contains_arbitrary_relative_paths(tmp_path: Path, segments: list[str]) -> None:
    rel = "/".join(segments)
    resolved = safe_path(tmp_path, rel)
    assert resolved.is_relative_to(tmp_path.resolve())


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
