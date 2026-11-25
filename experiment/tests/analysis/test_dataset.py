"""Unit tests for ``experiment.analysis.dataset``."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from experiment.analysis import (
    ASSERTION_COLUMNS,
    CELL_SUMMARY_COLUMNS,
    MEASUREMENT_COLUMNS,
    RunDataset,
)
from experiment.domain.run import (
    AssertionResult,
    CostAndProcessMetrics,
    EnvironmentPin,
    ExperimentRun,
    RunProvenance,
    TokenUsage,
    Treatment,
    TrialKey,
    TrialMeasurement,
    TrialRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_TASKS = REPO_ROOT / "experiment" / "tasks"


def test_run_dataset_projections_and_lazy_trial_inspection(packed_pilot_zip: Path) -> None:
    with RunDataset.from_zip(packed_pilot_zip) as dataset:
        assert dataset.run.run_id == "pilot-001"

        meas = dataset.measurements_df()
        assert list(meas.columns) == list(MEASUREMENT_COLUMNS)
        assert len(meas) == 6
        assert set(meas["paradigm"]) == {"typed_mcp", "codegen"}
        assert set(meas["task_success"]) == {1}

        preds = dataset.predicates_df(REAL_TASKS)
        assert preds.shape == (6, 10)
        assert not preds.isna().any().any()
        de9im = preds[preds["task_id"] == "analysis-de9im-001"]
        assert list(de9im["touches"]) == [1, 1]
        assert list(de9im["natural_breaks"]) == [0, 0]
        assert list(de9im["feature_count"]) == [0, 0]
        assert list(de9im["point_axis_order"]) == [0, 0]
        axis = preds[preds["task_id"] == "prep-axis-order-001"]
        assert list(axis["feature_count"]) == [1, 1]
        assert list(axis["point_axis_order"]) == [1, 1]
        assert list(axis["touches"]) == [0, 0]

        summary = dataset.cell_summary_df()
        assert list(summary.columns) == list(CELL_SUMMARY_COLUMNS)
        assert len(summary) == 6
        assert all(summary["pass_at_k"])
        assert all(summary["task_success_rate"] == 1.0)
        assert all(summary["predicate_score_median"] == 1.0)

        asserts = dataset.assertions_df(REAL_TASKS)
        assert list(asserts.columns) == list(ASSERTION_COLUMNS)
        assert len(asserts) == 8
        assert set(asserts["tier"]) <= {"trivial", "spatial", "value"}

        trial_id = "analysis-de9im-001/typed_mcp/semantic_repair/rep-1"
        handle = dataset.trial(trial_id)
        assert isinstance(handle.transcript, list)
        assert len(handle.transcript) >= 1
        assert handle.deliverable is not None


def test_predicates_and_assertions_fail_loudly_on_unknown_assertion() -> None:
    key = TrialKey(
        task_id="analysis-de9im-001",
        paradigm="codegen",
        enforcement_level="none",
        repetition=1,
    )
    record = TrialRecord(
        key=key,
        treatment=Treatment(paradigm="codegen", enforcement_level="none"),
        driver="scripted",
        status="ok",
    )
    meas = TrialMeasurement.from_assertions(
        key=key,
        assertions=(
            AssertionResult(
                assertion_id="mystery-assertion",
                tier="spatial",
                passed=True,
                detail="ok",
            ),
        ),
        economics=CostAndProcessMetrics(
            wall_seconds=1.5,
            tokens=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        ),
    )
    run = ExperimentRun(
        run_id="bad-assert",
        stage="pilot",
        created_at=datetime.now(UTC),
        provenance=RunProvenance(environment=EnvironmentPin()),
        trials={key.slug: record},
        measurements={key.slug: meas},
    )
    ds = RunDataset.from_run(run)
    with pytest.raises(ValueError, match="mystery-assertion"):
        ds.predicates_df(REAL_TASKS)
    with pytest.raises(ValueError, match="mystery-assertion"):
        ds.assertions_df(REAL_TASKS)
    with pytest.raises(RuntimeError, match="zip-backed"):
        ds.trial(key)

    empty_run = ExperimentRun(
        run_id="empty",
        stage="preflight",
        created_at=datetime.now(UTC),
        provenance=RunProvenance(environment=EnvironmentPin()),
    )
    empty_summary = RunDataset.from_run(empty_run).cell_summary_df()
    assert empty_summary.empty
    assert list(empty_summary.columns) == list(CELL_SUMMARY_COLUMNS)


def test_analysis_path_contains_no_cache_reads_or_imports() -> None:
    analysis_dir = REPO_ROOT / "experiment" / "src" / "experiment" / "analysis"
    for py_file in sorted(analysis_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "llm_cache" not in alias.name
                    assert "cache_key" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "llm_cache" not in mod
                assert "cache_key" not in mod
