"""Unit tests for analysis data preparation.

The predicate matrix itself is specified in ``features/analysis.feature`` and
driven through the CLI. What remains here is the predicate mapping's shape,
which is not exposed directly by the command.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from experiment import analyze

# The task document is validated on load, so these fixtures must be complete
# tasks rather than the two fields the predicate mapping reads.
_CONTEXT = {
    "schema_version": 1,
    "title": "fixture task",
    "prompt": "fixture prompt",
    "family": "A",
    "difficulty_rubric": {
        "tier": 2,
        "n_tools_human": 1,
        "n_steps_human": 1,
        "expressible": "medium",
    },
    "provenance": {
        "source": "constructed",
        "source_url": "https://example.invalid",
        "source_file": "fixture.geojson",
        "source_commit": "0" * 40,
        "license": "CC0",
        "contamination": "constructed",
    },
    "fixtures": {"input": "fixtures/fixture.geojson"},
    "human_baseline": {
        "status": "pending",
        "artifact_dir": "baselines/fixture",
        "produced_with": None,
        "human_time_min": None,
        "human_steps": None,
        "human_tools": [],
    },
    "budget_bounds": {"max_tool_calls": 10, "max_wall_s": 60},
    "runs": 2,
    "required_traps": [],
}

TASKS = {
    "analysis-de9im-001.yaml": {
        **_CONTEXT,
        "id": "analysis-de9im-001",
        "oracle": {
            "determinism_runs": 3,
            "assertions": [
                {"id": "shared-boundary-relation", "type": "de9im_relation", "predicate": "touches"}
            ],
        },
    },
    "prep-axis-order-001.yaml": {
        **_CONTEXT,
        "id": "prep-axis-order-001",
        "oracle": {
            "determinism_runs": 3,
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
            ],
        },
    },
}


def _write_tasks(root: Path) -> Path:
    tasks = root / "tasks"
    tasks.mkdir()
    for name, doc in TASKS.items():
        (tasks / name).write_text(yaml.safe_dump(doc), encoding="utf-8")
    return tasks


def test_load_predicates_roundtrip(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
    assert analyze.load_predicates(tasks) == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
    }


def test_real_suite_predicates_unique_and_present() -> None:
    repo = Path(__file__).resolve().parents[2]
    mapping = analyze.load_predicates(repo / "experiment" / "tasks")
    assert mapping == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
        "natural-breaks-assignments": "natural_breaks",
    }
