"""Unit tests for analysis data preparation.

The predicate matrix itself is specified in ``features/analysis.feature`` and
driven through the CLI. What remains here are the predicate mapping's shape and
the helper's exception type, neither of which is exposed directly by the command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from cli_harness import check, write_cell

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


def test_unknown_assertion_raises_value_error(results: dict) -> None:
    write_cell(results, "analysis-de9im-001", "B", [check("mystery-assertion", True)])
    with pytest.raises(ValueError, match="mystery-assertion"):
        analyze.flatten_rows(results["dir"], results["tasks"])


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
    assert len(mapping) == len(set(mapping.values()))


def test_load_predicates_rejects_missing_predicate_key(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    doc = {
        **_CONTEXT,
        "id": "missing-pred-001",
        "oracle": {
            "determinism_runs": 3,
            "assertions": [{"id": "unmapped-assertion", "type": "de9im_relation"}],
        },
    }
    (tasks / "missing-pred-001.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="missing a predicate"):
        analyze.load_predicates(tasks)


def test_load_predicates_rejects_duplicate_predicate_slug(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    doc = {
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
    (tasks / "dup-pred-001.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="1:1"):
        analyze.load_predicates(tasks)


def test_flatten_full_pilot_results_matrix_shape_mapping_and_cross_task_zeros(
    tmp_path: Path,
) -> None:
    import json

    from experiment.services import runs

    repo = Path(__file__).resolve().parents[2]
    tasks_root = repo / "experiment" / "tasks"
    out_dir = tmp_path / "pilot-run"
    spec = runs.parse_run_spec("scripted", None, None, "both", "all", "local")
    runs.run_experiment(tasks_root, spec, out_dir)

    df = analyze.flatten(out_dir, tasks_root)
    assert df.shape == (6, 9)
    assert list(df.columns) == [
        "run_id",
        "task",
        "arm",
        "driver",
        "model",
        "feature_count",
        "natural_breaks",
        "point_axis_order",
        "touches",
    ]
    # Every assertion emitted by the pilot maps 1:1 to the suite predicates (no missing, no orphans)
    emitted: set[str] = set()
    for score_file in out_dir.rglob("score.json"):
        data = json.loads(score_file.read_text(encoding="utf-8"))
        emitted.update(c["assertion_id"] for c in data["checks"])
    mapping = analyze.load_predicates(tasks_root)
    assert emitted == set(mapping.keys())
    assert len(mapping) == len(set(mapping.values()))

    # Cross-task zero semantics: cells score 1 on their own predicates and 0 on other tasks'
    de9im = df[df["task"] == "analysis-de9im-001"]
    assert list(de9im["touches"]) == [1, 1]
    assert list(de9im["natural_breaks"]) == [0, 0]
    assert list(de9im["feature_count"]) == [0, 0]
    assert list(de9im["point_axis_order"]) == [0, 0]

    jenks = df[df["task"] == "cartography-jenks-001"]
    assert list(jenks["natural_breaks"]) == [1, 1]
    assert list(jenks["touches"]) == [0, 0]

    axis = df[df["task"] == "prep-axis-order-001"]
    assert list(axis["feature_count"]) == [1, 1]
    assert list(axis["point_axis_order"]) == [1, 1]
    assert list(axis["touches"]) == [0, 0]
