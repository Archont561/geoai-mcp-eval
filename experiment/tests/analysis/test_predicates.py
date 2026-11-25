"""Unit tests for ``experiment.analysis.predicates``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from experiment.analysis import load_predicates, task_predicates

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_TASKS = REPO_ROOT / "experiment" / "tasks"

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


def test_load_predicates_and_task_predicates_roundtrip(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    docs = {
        "analysis-de9im-001.yaml": {
            **_CONTEXT,
            "id": "analysis-de9im-001",
            "oracle": {
                "determinism_runs": 3,
                "assertions": [
                    {
                        "id": "shared-boundary-relation",
                        "type": "de9im_relation",
                        "predicate": "touches",
                    }
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
    for name, doc in docs.items():
        (tasks / name).write_text(yaml.safe_dump(doc), encoding="utf-8")

    assert load_predicates(tasks) == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
    }
    assert task_predicates(tasks) == {
        "analysis-de9im-001": ("touches",),
        "prep-axis-order-001": ("feature_count", "point_axis_order"),
    }


def test_real_suite_predicates_unique_and_present() -> None:
    mapping = load_predicates(REAL_TASKS)
    assert mapping == {
        "shared-boundary-relation": "touches",
        "single-output-feature": "feature_count",
        "representative-point-axis-order": "point_axis_order",
        "natural-breaks-assignments": "natural_breaks",
    }
    assert len(mapping) == len(set(mapping.values()))


def test_load_predicates_rejects_missing_and_duplicate_keys(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()
    doc = {
        **_CONTEXT,
        "id": "missing-pred-001",
        "oracle": {
            "determinism_runs": 3,
            "assertions": [{"id": "unmapped-assertion", "type": "de9im_relation"}],
        },
    }
    (missing_dir / "missing-pred-001.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="missing a predicate"):
        load_predicates(missing_dir)

    dup_dir = tmp_path / "dup"
    dup_dir.mkdir()
    dup_doc = {
        **_CONTEXT,
        "id": "dup-pred-001",
        "oracle": {
            "determinism_runs": 3,
            "assertions": [
                {"id": "first-check", "type": "de9im_relation", "predicate": "touches"},
                {"id": "second-check", "type": "de9im_relation", "predicate": "touches"},
            ],
        },
    }
    (dup_dir / "dup-pred-001.yaml").write_text(yaml.safe_dump(dup_doc), encoding="utf-8")
    with pytest.raises(ValueError, match="1:1"):
        load_predicates(dup_dir)
