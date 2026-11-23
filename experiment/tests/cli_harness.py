"""Fixtures and helpers for the experiment CLI's behavioural scenarios.

This module is deliberately not named ``conftest.py``: pytest imports conftest
files under a bare basename, so two ``conftest.py`` modules in one run (here and
in ``experiment-qgis-plugin/tests``) collide. Helpers are imported from here by
name; ``conftest.py`` re-exports the fixtures pytest needs to see.

Every scenario runs the *whole* Typer application — ``experiment.cli._loader
.app``, the same object ``python -m experiment`` mounts — so a scenario failure
means a real command misbehaves, not that a helper changed shape.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"
UTF8 = "utf-8"


@pytest.fixture()
def cli() -> CliRunner:
    """A Typer runner that keeps stdout and stderr apart."""
    return CliRunner()


@pytest.fixture()
def suite(tmp_path: Path) -> dict[str, Any]:
    """A writable copy of the shipped pilot task suite."""
    root = tmp_path / "tasks"
    shutil.copytree(TASK_ROOT, root)
    return {"root": root, "path": str(root)}


@pytest.fixture()
def results(tmp_path: Path) -> dict[str, Any]:
    """A results directory with a task suite and one scored run per arm."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "analysis-de9im-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "analysis-de9im-001",
                "oracle": {
                    "assertions": [
                        {
                            "id": "shared-boundary-relation",
                            "type": "de9im_relation",
                            "predicate": "touches",
                        }
                    ]
                },
            }
        ),
        encoding=UTF8,
    )
    (tasks / "prep-axis-order-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "prep-axis-order-001",
                "oracle": {
                    "assertions": [
                        {
                            "id": "single-output-feature",
                            "type": "geojson_feature_count",
                            "predicate": "feature_count",
                        },
                        {
                            "id": "representative-point-axis-order",
                            "type": "representative_point_matches",
                            "predicate": "point_axis_order",
                        },
                    ]
                },
            }
        ),
        encoding=UTF8,
    )
    return {"dir": tmp_path / "results", "tasks": tasks, "cells": []}


def write_cell(
    results: dict[str, Any],
    task: str,
    arm: str,
    checks: list[dict[str, Any]],
    *,
    run_id: str = "r1",
) -> None:
    """Write one prototype cell's ``score.json`` into the results directory."""
    cell = results["dir"] / task / f"arm-{arm}"
    cell.mkdir(parents=True, exist_ok=True)
    payload = {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "meta": {
            "run_id": run_id,
            "task": task,
            "arm": arm,
            "driver": "ollama",
            "model": "m",
            "status": "ok",
            "error": None,
            "wall_s": 1.0,
            "oracle_passed": all(check["passed"] for check in checks),
            "prototype": True,
        },
    }
    (cell / "score.json").write_text(json.dumps(payload), encoding=UTF8)
    results["cells"].append((task, arm))


def check(assertion_id: str, passed: bool) -> dict[str, Any]:
    return {"assertion_id": assertion_id, "passed": passed, "message": "m"}


# --- artefacts for the determinism gate -------------------------------------


def write_point_artifact(root: Path) -> None:
    from shapely.geometry import shape

    fixture = TASK_ROOT / "fixtures/prepare/poland.geojson"
    source = json.loads(fixture.read_text(encoding=UTF8))["features"][0]
    point = shape(source["geometry"]).representative_point()
    write_json(
        root / "prep-axis-order-001/result.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"ADMIN": "Poland", "ISO_A3": "POL"},
                    "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
                }
            ],
        },
    )


def write_relation_artifact(root: Path) -> None:
    write_json(
        root / "analysis-de9im-001/result.json",
        {"relation": "touches", "de9im": "FF2F11212"},
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


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding=UTF8)
