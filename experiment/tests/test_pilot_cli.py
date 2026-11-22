"""CLI command integration tests for pilot preparation and oracle runs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from experiment.cli.pilot import app


def write_point_artifact(root: Path) -> None:
    from shapely.geometry import shape

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
    write_json(
        root / "analysis-de9im-001/result.json", {"relation": "touches", "de9im": "FF2F11212"}
    )


def write_jenks_artifact(root: Path) -> None:
    write_json(
        root / "cartography-jenks-001/result.json",
        {
            "method": "jenks",
            "class_count": 4,
            "breaks": [44385155.0, 126264931.0, 328239523.0, 1397715000.0],
            "assignments": {
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
            },
        },
    )


def write_expected_artifacts(root: Path) -> None:
    write_point_artifact(root)
    write_relation_artifact(root)
    write_jenks_artifact(root)


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding="utf-8")


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"


def test_validate_command_reports_success_and_suite_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--root", str(TASK_ROOT)])
    assert result.exit_code == 0
    assert "Task suite valid: 3 tasks" in result.stdout

    root = tmp_path / "tasks"
    shutil.copytree(TASK_ROOT, root)
    (root / "schema-v1.json").unlink()
    result = runner.invoke(app, ["validate", "--root", str(root)])
    assert result.exit_code == 1
    assert "cannot read schema" in result.stdout


def invoke_determinism(runner: CliRunner, task_id: str, artifacts_dir: Path) -> Any:
    return runner.invoke(
        app,
        [
            "determinism",
            task_id,
            "--artifacts-dir",
            str(artifacts_dir),
            "--root",
            str(TASK_ROOT),
        ],
    )


def test_determinism_command_outputs_report_and_nonzero_for_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    artifact_root = tmp_path / "artifacts"
    write_expected_artifacts(artifact_root)
    result = invoke_determinism(
        runner, "cartography-jenks-001", artifact_root / "cartography-jenks-001"
    )
    report = json.loads(result.stdout)
    assert result.exit_code == 0
    assert report["passed"] is True
    assert len(report["run_results"]) == 3

    failure = invoke_determinism(runner, "prep-axis-order-001", tmp_path / "missing")
    assert failure.exit_code == 1
    assert json.loads(failure.stdout)["passed"] is False


def test_determinism_command_rejects_unknown_task(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "determinism",
            "unknown-task",
            "--artifacts-dir",
            str(tmp_path),
            "--root",
            str(TASK_ROOT),
        ],
    )
    assert result.exit_code != 0
    assert "unknown task ID" in result.output
