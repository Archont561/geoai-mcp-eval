"""Behavioral tests for pilot scoring and the three-pass determinism gate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from shapely.geometry import shape

from experiment.oracle import (
    AssertionResult,
    OracleVerdict,
    evaluate_task,
    fisher_jenks_breaks,
    run_determinism_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
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
    "DEU": 2,
    "JPN": 2,
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
    path.write_text(json.dumps(content), encoding="utf-8")


def write_point_artifact(root: Path) -> None:
    fixture = TASK_ROOT / "fixtures/prepare/poland.geojson"
    source = json.loads(fixture.read_text(encoding="utf-8"))["features"][0]
    point = shape(source["geometry"]).representative_point()
    feature = {
        "type": "Feature",
        "properties": {"ADMIN": "Poland", "ISO_A3": "POL"},
        "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
    }
    write_json(
        root / "prep-axis-order-001/result.geojson",
        {"type": "FeatureCollection", "features": [feature]},
    )


def write_relation_artifact(root: Path) -> None:
    fixture = TASK_ROOT / "fixtures/analysis/poland-czechia.geojson"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    geometries = {
        feature["properties"]["ISO_A3"]: shape(feature["geometry"]) for feature in data["features"]
    }
    relation = geometries["POL"].relate(geometries["CZE"])
    write_json(root / "analysis-de9im-001/result.json", {"relation": "touches", "de9im": relation})


def write_jenks_artifact(root: Path) -> None:
    write_json(
        root / "cartography-jenks-001/result.json",
        {
            "method": "jenks",
            "class_count": 4,
            "breaks": EXPECTED_BREAKS,
            "assignments": EXPECTED_CLASSES,
        },
    )


def write_expected_artifacts(root: Path) -> None:
    write_point_artifact(root)
    write_relation_artifact(root)
    write_jenks_artifact(root)


def test_each_pilot_oracle_accepts_its_expected_artifact(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)

    for task_id in ("prep-axis-order-001", "analysis-de9im-001", "cartography-jenks-001"):
        verdict = evaluate_task(task_path(task_id), tmp_path / task_id)
        assert verdict.passed, verdict.to_dict()


def test_task_oracle_detects_swapped_longitude_and_latitude(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    output_path = tmp_path / "prep-axis-order-001/result.geojson"
    result = json.loads(output_path.read_text(encoding="utf-8"))
    coordinates = result["features"][0]["geometry"]["coordinates"]
    result["features"][0]["geometry"]["coordinates"] = coordinates[::-1]
    write_json(output_path, result)

    verdict = evaluate_task(task_path("prep-axis-order-001"), output_path.parent)

    assert not verdict.passed
    assert any("expected lon/lat" in check.message for check in verdict.checks)


def test_task_oracle_detects_wrong_topology_and_jenks_results(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    relation_path = tmp_path / "analysis-de9im-001/result.json"
    relation = json.loads(relation_path.read_text(encoding="utf-8"))
    relation["de9im"] = "FFFFFFFFF"
    write_json(relation_path, relation)
    jenks_path = tmp_path / "cartography-jenks-001/result.json"
    jenks = json.loads(jenks_path.read_text(encoding="utf-8"))
    jenks["assignments"]["USA"] = 4
    write_json(jenks_path, jenks)

    relation_verdict = evaluate_task(task_path("analysis-de9im-001"), relation_path.parent)
    jenks_verdict = evaluate_task(task_path("cartography-jenks-001"), jenks_path.parent)

    assert not relation_verdict.passed
    assert not jenks_verdict.passed


def test_representative_point_oracle_rejects_missing_id_wrong_geometry_and_bad_coordinates(
    tmp_path: Path,
) -> None:
    write_expected_artifacts(tmp_path)
    output_path = tmp_path / "prep-axis-order-001/result.geojson"
    result = json.loads(output_path.read_text(encoding="utf-8"))
    result["features"][0]["properties"] = {"ADMIN": "Poland", "ISO_A3": "CZE"}
    write_json(output_path, result)
    verdict = evaluate_task(task_path("prep-axis-order-001"), output_path.parent)
    assert not verdict.passed
    assert "must preserve ISO_A3='POL'" in verdict.checks[1].message

    result["features"][0]["properties"]["ISO_A3"] = "POL"
    result["features"][0]["geometry"] = {"type": "LineString", "coordinates": []}
    write_json(output_path, result)
    verdict = evaluate_task(task_path("prep-axis-order-001"), output_path.parent)
    assert not verdict.passed
    assert "must be a GeoJSON Point" in verdict.checks[1].message

    result["features"][0]["geometry"] = {"type": "Point", "coordinates": [1]}
    write_json(output_path, result)
    verdict = evaluate_task(task_path("prep-axis-order-001"), output_path.parent)
    assert not verdict.passed
    assert "[longitude, latitude]" in verdict.checks[1].message


def test_geojson_feature_count_and_oracle_path_traversal(tmp_path: Path) -> None:
    from experiment.oracle import _evaluate_assertion

    assertion = {
        "id": "count",
        "type": "geojson_feature_count",
        "output": "result.geojson",
        "expected": 0,
    }
    write_json(tmp_path / "result.geojson", {"type": "FeatureCollection", "features": []})
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
    relation = json.loads(relation_path.read_text(encoding="utf-8"))
    relation["explanation"] = "unexpected"
    write_json(relation_path, relation)
    assert not evaluate_task(task_path("analysis-de9im-001"), relation_path.parent).passed

    jenks_path = tmp_path / "cartography-jenks-001/result.json"
    jenks = json.loads(jenks_path.read_text(encoding="utf-8"))
    jenks["notes"] = "unexpected"
    write_json(jenks_path, jenks)
    assert not evaluate_task(task_path("cartography-jenks-001"), jenks_path.parent).passed


def test_oracle_rejects_invalid_geojson_output(tmp_path: Path) -> None:
    output_path = tmp_path / "bad.geojson"
    assertion = {
        "id": "count",
        "type": "geojson_feature_count",
        "output": "bad.geojson",
        "expected": 0,
    }
    _assert_invalid_outputs_rejected(output_path, assertion, tmp_path)


def _assert_invalid_outputs_rejected(
    output_path: Path, assertion: dict[str, object], root: Path
) -> None:
    from experiment.oracle import _evaluate_assertion

    for invalid in ({"type": "Feature", "features": []}, []):
        write_json(output_path, invalid)
        try:
            _evaluate_assertion(assertion, root, root)
        except ValueError:
            continue
        raise AssertionError("invalid GeoJSON outputs must be rejected")


def test_missing_output_fails_with_an_actionable_check(tmp_path: Path) -> None:
    verdict = evaluate_task(task_path("prep-axis-order-001"), tmp_path)

    assert not verdict.passed
    assert all("could not evaluate assertion" in check.message for check in verdict.checks)


def test_fisher_jenks_known_fixture_and_invalid_inputs() -> None:
    assert fisher_jenks_breaks([1, 2, 3, 100, 101, 102], 2) == [3.0, 102.0]
    assert fisher_jenks_breaks([8, 3, 6], 1) == [8.0]
    for values, classes in (([], 1), ([1, 2], 0), ([1, 1], 2)):
        try:
            fisher_jenks_breaks(values, classes)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid Jenks input must be rejected")


def test_determinism_gate_passes_three_identical_oracle_runs(tmp_path: Path) -> None:
    write_expected_artifacts(tmp_path)
    report = run_determinism_gate(
        task_path("cartography-jenks-001"), tmp_path / "cartography-jenks-001"
    )

    assert report.passed
    assert report.required_runs == 3
    assert report.consistent
    assert [result["status"] for result in report.run_results] == ["passed"] * 3


def test_determinism_gate_rejects_inconsistent_and_missing_verdicts(tmp_path: Path) -> None:
    path = task_path("prep-axis-order-001")
    sequence = iter(
        [
            OracleVerdict(True, (AssertionResult("check", True, "pass"),)),
            OracleVerdict(False, (AssertionResult("check", False, "fail"),)),
            OracleVerdict(True, (AssertionResult("check", True, "pass"),)),
        ]
    )
    inconsistent = run_determinism_gate(path, tmp_path, lambda *_: next(sequence))
    assert not inconsistent.passed
    assert not inconsistent.consistent

    missing_sequence = iter(
        [
            OracleVerdict(True, (AssertionResult("check", True, "pass"),)),
            None,
            OracleVerdict(True, (AssertionResult("check", True, "pass"),)),
        ]
    )
    missing = run_determinism_gate(path, tmp_path, lambda *_: next(missing_sequence))
    assert not missing.passed
    assert not missing.consistent
    assert any("missing" in issue for issue in missing.issues)


def test_determinism_gate_records_exception_and_rejects_bad_run_count(tmp_path: Path) -> None:
    def explode(*_args: object) -> OracleVerdict:
        raise RuntimeError("simulated oracle failure")

    report = run_determinism_gate(task_path("prep-axis-order-001"), tmp_path, explode)
    assert not report.passed
    assert any("simulated oracle failure" in issue for issue in report.issues)

    task_yaml = task_path("prep-axis-order-001")
    task = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
    task["oracle"]["determinism_runs"] = 2
    bad_task_path = tmp_path / "bad-runs.yaml"
    bad_task_path.write_text(yaml.safe_dump(task), encoding="utf-8")
    bad_report = run_determinism_gate(bad_task_path, tmp_path)
    assert not bad_report.passed
    assert any("exactly 3" in issue for issue in bad_report.issues)
