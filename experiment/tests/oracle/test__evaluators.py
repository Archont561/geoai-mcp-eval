"""Unit tests for ``experiment.oracle._evaluators``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.oracle import _evaluate_assertion, evaluate_task

UTF8 = "utf-8"
FEATURES_KEY = "features"
TYPE_KEY = "type"
AXIS_TASK = "prep-axis-order-001"


def test_each_pilot_oracle_accepts_its_expected_artifact(
    expected_artifacts_dir: Path,
    pilot_task_paths: dict[str, Path],
) -> None:
    for task_id in (AXIS_TASK, "analysis-de9im-001", "cartography-jenks-001"):
        verdict = evaluate_task(pilot_task_paths[task_id], expected_artifacts_dir / task_id)
        assert verdict.passed, verdict.to_dict()


def test_task_oracle_detects_swapped_longitude_and_latitude(
    expected_artifacts_dir: Path,
    pilot_task_paths: dict[str, Path],
) -> None:
    output_path = expected_artifacts_dir / "prep-axis-order-001/result.geojson"
    result = json.loads(output_path.read_text(encoding=UTF8))
    coordinates = result[FEATURES_KEY][0]["geometry"]["coordinates"]
    result[FEATURES_KEY][0]["geometry"]["coordinates"] = coordinates[::-1]
    output_path.write_text(json.dumps(result), encoding=UTF8)

    verdict = evaluate_task(pilot_task_paths[AXIS_TASK], output_path.parent)
    assert not verdict.passed
    assert any("expected lon/lat" in check.message for check in verdict.checks)


def test_task_oracle_detects_wrong_topology_and_jenks_results(
    expected_artifacts_dir: Path,
    pilot_task_paths: dict[str, Path],
) -> None:
    relation_path = expected_artifacts_dir / "analysis-de9im-001/result.json"
    relation = json.loads(relation_path.read_text(encoding=UTF8))
    relation["de9im"] = "FFFFFFFFF"
    relation_path.write_text(json.dumps(relation), encoding=UTF8)

    jenks_path = expected_artifacts_dir / "cartography-jenks-001/result.json"
    jenks = json.loads(jenks_path.read_text(encoding=UTF8))
    jenks["assignments"]["USA"] = 4
    jenks_path.write_text(json.dumps(jenks), encoding=UTF8)

    assert not evaluate_task(pilot_task_paths["analysis-de9im-001"], relation_path.parent).passed
    assert not evaluate_task(pilot_task_paths["cartography-jenks-001"], jenks_path.parent).passed


def test_representative_point_oracle_rejects_missing_id_wrong_geometry_and_bad_coordinates(
    expected_artifacts_dir: Path,
    pilot_task_paths: dict[str, Path],
) -> None:
    output_path = expected_artifacts_dir / "prep-axis-order-001/result.geojson"
    result = json.loads(output_path.read_text(encoding=UTF8))
    result[FEATURES_KEY][0]["properties"] = {"ADMIN": "Poland", "ISO_A3": "CZE"}
    output_path.write_text(json.dumps(result), encoding=UTF8)
    verdict = evaluate_task(pilot_task_paths[AXIS_TASK], output_path.parent)
    assert not verdict.passed
    assert "must preserve ISO_A3='POL'" in verdict.checks[1].message

    result[FEATURES_KEY][0]["properties"]["ISO_A3"] = "POL"
    result[FEATURES_KEY][0]["geometry"] = {TYPE_KEY: "LineString", "coordinates": []}
    output_path.write_text(json.dumps(result), encoding=UTF8)
    verdict = evaluate_task(pilot_task_paths[AXIS_TASK], output_path.parent)
    assert not verdict.passed
    assert "must be a GeoJSON Point" in verdict.checks[1].message

    result[FEATURES_KEY][0]["geometry"] = {TYPE_KEY: "Point", "coordinates": [1]}
    output_path.write_text(json.dumps(result), encoding=UTF8)
    verdict = evaluate_task(pilot_task_paths[AXIS_TASK], output_path.parent)
    assert not verdict.passed
    assert "[longitude, latitude]" in verdict.checks[1].message


def test_geojson_feature_count_and_oracle_path_traversal(tmp_path: Path) -> None:
    assertion = {
        "id": "count",
        TYPE_KEY: "geojson_feature_count",
        "output": "result.geojson",
        "expected": 0,
    }
    (tmp_path / "result.geojson").write_text(
        json.dumps({TYPE_KEY: "FeatureCollection", FEATURES_KEY: []}), encoding=UTF8
    )
    assert _evaluate_assertion(assertion, tmp_path, tmp_path).passed
    assertion["expected"] = 1
    assert not _evaluate_assertion(assertion, tmp_path, tmp_path).passed
    assertion["output"] = "../outside.json"
    with pytest.raises(ValueError, match="escapes"):
        _evaluate_assertion(assertion, tmp_path, tmp_path)


def test_oracle_rejects_extra_output_fields(
    expected_artifacts_dir: Path,
    pilot_task_paths: dict[str, Path],
) -> None:
    relation_path = expected_artifacts_dir / "analysis-de9im-001/result.json"
    relation = json.loads(relation_path.read_text(encoding=UTF8))
    relation["explanation"] = "unexpected"
    relation_path.write_text(json.dumps(relation), encoding=UTF8)
    assert not evaluate_task(pilot_task_paths["analysis-de9im-001"], relation_path.parent).passed

    jenks_path = expected_artifacts_dir / "cartography-jenks-001/result.json"
    jenks = json.loads(jenks_path.read_text(encoding=UTF8))
    jenks["notes"] = "unexpected"
    jenks_path.write_text(json.dumps(jenks), encoding=UTF8)
    assert not evaluate_task(pilot_task_paths["cartography-jenks-001"], jenks_path.parent).passed


@pytest.mark.parametrize("invalid", [{TYPE_KEY: "Feature", FEATURES_KEY: []}, []])
def test_oracle_rejects_invalid_geojson_output(tmp_path: Path, invalid: object) -> None:
    output_path = tmp_path / "bad.geojson"
    output_path.write_text(json.dumps(invalid), encoding=UTF8)
    assertion = {
        "id": "count",
        TYPE_KEY: "geojson_feature_count",
        "output": "bad.geojson",
        "expected": 0,
    }
    with pytest.raises(ValueError):
        _evaluate_assertion(assertion, tmp_path, tmp_path)


def test_missing_output_fails_with_an_actionable_check(
    tmp_path: Path, pilot_task_paths: dict[str, Path]
) -> None:
    verdict = evaluate_task(pilot_task_paths[AXIS_TASK], tmp_path)
    assert not verdict.passed
    assert all("could not evaluate assertion" in check.message for check in verdict.checks)
