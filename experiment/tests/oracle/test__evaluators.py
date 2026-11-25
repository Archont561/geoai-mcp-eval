"""Unit tests for ``experiment.oracle._evaluators``."""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import shape

from experiment.oracle import _evaluate_assertion, evaluate_task

UTF8 = "utf-8"
FEATURES_KEY = "features"
TYPE_KEY = "type"
AXIS_TASK = "prep-axis-order-001"
TWO = 2

REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"
EXPECTED_BREAKS = [44385155.0, 126264931.0, 328239523.0, 1397715000.0]
EXPECTED_CLASSES = {
    "LTU": 1,
    "SVK": 1,
    "AUT": 1,
    "HUN": 1,
    "CZE": 1,
    "POL": 1,
    "UKR": 1,
    "DEU": TWO,
    "JPN": TWO,
    "USA": 3,
    "IND": 4,
    "CHN": 4,
}


def task_path(task_id: str) -> Path:
    for path in TASK_ROOT.glob("*.yaml"):
        if path.stem.startswith(task_id):
            return path
    raise AssertionError(f"test task not found: {task_id}")


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding=UTF8)


def write_expected_artifacts(root: Path) -> None:
    fixture = TASK_ROOT / "fixtures/prepare/poland.geojson"
    source = json.loads(fixture.read_text(encoding=UTF8))[FEATURES_KEY][0]
    point = shape(source["geometry"]).representative_point()
    feature = {
        TYPE_KEY: "Feature",
        "properties": {"ADMIN": "Poland", "ISO_A3": "POL"},
        "geometry": {TYPE_KEY: "Point", "coordinates": [point.x, point.y]},
    }
    write_json(
        root / "prep-axis-order-001/result.geojson",
        {TYPE_KEY: "FeatureCollection", FEATURES_KEY: [feature]},
    )

    rel_fixture = TASK_ROOT / "fixtures/analysis/poland-czechia.geojson"
    data = json.loads(rel_fixture.read_text(encoding=UTF8))
    geometries = {
        feat["properties"]["ISO_A3"]: shape(feat["geometry"]) for feat in data[FEATURES_KEY]
    }
    relation = geometries["POL"].relate(geometries["CZE"])
    write_json(root / "analysis-de9im-001/result.json", {"relation": "touches", "de9im": relation})

    write_json(
        root / "cartography-jenks-001/result.json",
        {
            "method": "jenks",
            "class_count": 4,
            "breaks": EXPECTED_BREAKS,
            "assignments": EXPECTED_CLASSES,
        },
    )


def test_each_pilot_oracle_accepts_its_expected_artifact(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    for task_id in (AXIS_TASK, "analysis-de9im-001", "cartography-jenks-001"):
        verdict = evaluate_task(task_path(task_id), tmp_path / task_id)
        assert verdict.passed, verdict.to_dict()


def test_task_oracle_detects_swapped_longitude_and_latitude(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    output_path = tmp_path / "prep-axis-order-001/result.geojson"
    result = json.loads(output_path.read_text(encoding=UTF8))
    coordinates = result[FEATURES_KEY][0]["geometry"]["coordinates"]
    result[FEATURES_KEY][0]["geometry"]["coordinates"] = coordinates[::-1]
    write_json(output_path, result)

    verdict = evaluate_task(task_path(AXIS_TASK), output_path.parent)
    assert not verdict.passed
    assert any("expected lon/lat" in check.message for check in verdict.checks)


def test_task_oracle_detects_wrong_topology_and_jenks_results(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    relation_path = tmp_path / "analysis-de9im-001/result.json"
    relation = json.loads(relation_path.read_text(encoding=UTF8))
    relation["de9im"] = "FFFFFFFFF"
    write_json(relation_path, relation)
    jenks_path = tmp_path / "cartography-jenks-001/result.json"
    jenks = json.loads(jenks_path.read_text(encoding=UTF8))
    jenks["assignments"]["USA"] = 4
    write_json(jenks_path, jenks)

    assert not evaluate_task(task_path("analysis-de9im-001"), relation_path.parent).passed
    assert not evaluate_task(task_path("cartography-jenks-001"), jenks_path.parent).passed


def test_representative_point_oracle_rejects_missing_id_wrong_geometry_and_bad_coordinates(
    tmp_path: Path,
) -> None:
    write_expected_artifacts(tmp_path)
    output_path = tmp_path / "prep-axis-order-001/result.geojson"
    result = json.loads(output_path.read_text(encoding=UTF8))
    result[FEATURES_KEY][0]["properties"] = {"ADMIN": "Poland", "ISO_A3": "CZE"}
    write_json(output_path, result)
    verdict = evaluate_task(task_path(AXIS_TASK), output_path.parent)
    assert not verdict.passed
    assert "must preserve ISO_A3='POL'" in verdict.checks[1].message

    result[FEATURES_KEY][0]["properties"]["ISO_A3"] = "POL"
    result[FEATURES_KEY][0]["geometry"] = {TYPE_KEY: "LineString", "coordinates": []}
    write_json(output_path, result)
    verdict = evaluate_task(task_path(AXIS_TASK), output_path.parent)
    assert not verdict.passed
    assert "must be a GeoJSON Point" in verdict.checks[1].message

    result[FEATURES_KEY][0]["geometry"] = {TYPE_KEY: "Point", "coordinates": [1]}
    write_json(output_path, result)
    verdict = evaluate_task(task_path(AXIS_TASK), output_path.parent)
    assert not verdict.passed
    assert "[longitude, latitude]" in verdict.checks[1].message


def test_geojson_feature_count_and_oracle_path_traversal(tmp_path: Path) -> None:
    assertion = {
        "id": "count",
        TYPE_KEY: "geojson_feature_count",
        "output": "result.geojson",
        "expected": 0,
    }
    write_json(tmp_path / "result.geojson", {TYPE_KEY: "FeatureCollection", FEATURES_KEY: []})
    assert _evaluate_assertion(assertion, tmp_path, tmp_path).passed
    assertion["expected"] = 1
    assert not _evaluate_assertion(assertion, tmp_path, tmp_path).passed
    assertion["output"] = "../outside.json"
    try:
        _evaluate_assertion(assertion, tmp_path, tmp_path)
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("oracle path traversal must be rejected")


def test_oracle_rejects_extra_output_fields(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    relation_path = tmp_path / "analysis-de9im-001/result.json"
    relation = json.loads(relation_path.read_text(encoding=UTF8))
    relation["explanation"] = "unexpected"
    write_json(relation_path, relation)
    assert not evaluate_task(task_path("analysis-de9im-001"), relation_path.parent).passed

    jenks_path = tmp_path / "cartography-jenks-001/result.json"
    jenks = json.loads(jenks_path.read_text(encoding=UTF8))
    jenks["notes"] = "unexpected"
    write_json(jenks_path, jenks)
    assert not evaluate_task(task_path("cartography-jenks-001"), jenks_path.parent).passed


def test_oracle_rejects_invalid_geojson_output(tmp_path: Path) -> None:
    output_path = tmp_path / "bad.geojson"
    assertion = {
        "id": "count",
        TYPE_KEY: "geojson_feature_count",
        "output": "bad.geojson",
        "expected": 0,
    }
    for invalid in ({TYPE_KEY: "Feature", FEATURES_KEY: []}, []):
        write_json(output_path, invalid)
        try:
            _evaluate_assertion(assertion, tmp_path, tmp_path)
        except ValueError:
            continue
        raise AssertionError("invalid GeoJSON outputs must be rejected")


def test_missing_output_fails_with_an_actionable_check(tmp_path: Path) -> None:
    verdict = evaluate_task(task_path(AXIS_TASK), tmp_path)
    assert not verdict.passed
    assert all("could not evaluate assertion" in check.message for check in verdict.checks)
