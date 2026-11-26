"""Unit tests for ``experiment.analysis.predicates``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.analysis import load_predicates, task_predicates

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


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(predicates=["touches", "feature_count", "point_axis_order"])
@given(
    predicates=st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
        min_size=3,
        max_size=3,
        unique=True,
    )
)
def test_load_predicates_and_task_predicates_roundtrip(
    tmp_path: Path, predicates: list[str]
) -> None:
    first, second, third = predicates
    tasks = tmp_path / "tasks"
    tasks.mkdir(exist_ok=True)
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
                        "predicate": first,
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
                        "predicate": second,
                    },
                    {
                        "id": "representative-point-axis-order",
                        "type": "representative_point_matches",
                        "predicate": third,
                    },
                ],
            },
        },
    }
    for name, doc in docs.items():
        (tasks / name).write_text(yaml.safe_dump(doc), encoding="utf-8")

    assert load_predicates(tasks) == {
        "shared-boundary-relation": first,
        "single-output-feature": second,
        "representative-point-axis-order": third,
    }
    assert task_predicates(tasks) == {
        "analysis-de9im-001": (first,),
        "prep-axis-order-001": tuple(sorted((second, third))),
    }


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(predicate="touches")
@given(predicate=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15))
def test_load_predicates_rejects_missing_and_duplicate_keys(tmp_path: Path, predicate: str) -> None:
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir(exist_ok=True)
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
    dup_dir.mkdir(exist_ok=True)
    dup_doc = {
        **_CONTEXT,
        "id": "dup-pred-001",
        "oracle": {
            "determinism_runs": 3,
            "assertions": [
                {"id": "first-check", "type": "de9im_relation", "predicate": predicate},
                {"id": "second-check", "type": "de9im_relation", "predicate": predicate},
            ],
        },
    }
    (dup_dir / "dup-pred-001.yaml").write_text(yaml.safe_dump(dup_doc), encoding="utf-8")
    with pytest.raises(ValueError, match="1:1"):
        load_predicates(dup_dir)
