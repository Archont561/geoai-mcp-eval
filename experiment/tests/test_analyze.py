"""Unit tests for the notebook-first analysis client and DataFrame projections (GEO-020)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from experiment.adapters.run_archive import RunArchive
from experiment.adapters.subprocess_runner import CommandResult
from experiment.analysis import (
    ASSERTION_COLUMNS,
    CELL_SUMMARY_COLUMNS,
    MEASUREMENT_COLUMNS,
    GitHubRunClient,
    GitHubRunError,
    RunDataset,
    load_predicates,
    task_predicates,
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
from experiment.services import archive as archive_service
from experiment.services import runs

REPO_ROOT = Path(__file__).resolve().parents[2]
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


def _build_packed_pilot_zip(tmp_path: Path) -> Path:
    out_dir = tmp_path / "pilot-run"
    spec = runs.parse_run_spec("scripted", None, None, "both", "all", "local")
    runs.run_experiment(REAL_TASKS, spec, out_dir)
    zip_path = tmp_path / "experiment-run-pilot-001.zip"
    archive_service.pack_archive(
        archive_service.PackOptions(
            source_dir=out_dir,
            output_zip=zip_path,
            run_id="pilot-001",
            stage="pilot",
            run_harvest=False,
        )
    )
    return zip_path


def test_load_predicates_and_task_predicates_roundtrip(tmp_path: Path) -> None:
    tasks = _write_tasks(tmp_path)
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


def test_run_dataset_projections_and_lazy_trial_inspection(tmp_path: Path) -> None:
    zip_path = _build_packed_pilot_zip(tmp_path)
    with RunDataset.from_zip(zip_path) as dataset:
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
        assert len(asserts) == 8  # (1 + 2 + 1) assertions * 2 paradigms
        assert set(asserts["tier"]) <= {"trivial", "spatial", "value"}

        # Lazy trial drill-down reads transcript & deliverable on demand
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
    meas = TrialMeasurement.build(
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

    # Empty run yields empty cell summary with expected schema
    empty_run = ExperimentRun(
        run_id="empty",
        stage="preflight",
        created_at=datetime.now(UTC),
        provenance=RunProvenance(environment=EnvironmentPin()),
    )
    empty_summary = RunDataset.from_run(empty_run).cell_summary_df()
    assert empty_summary.empty
    assert list(empty_summary.columns) == list(CELL_SUMMARY_COLUMNS)


def test_github_run_client_download_cache_list_latest_and_offline(tmp_path: Path) -> None:
    source_zip = _build_packed_pilot_zip(tmp_path / "src")
    calls: list[list[str]] = []

    def fake_runner(argv: Sequence[str]) -> CommandResult:
        cmd = list(argv)
        calls.append(cmd)
        if cmd[:3] == ["gh", "run", "list"]:
            payload = [
                {
                    "databaseId": 987654321,
                    "headSha": "deadbeef",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "2026-11-24T12:00:00Z",
                    "displayTitle": "Experiment",
                    "url": "https://github.com/org/repo/actions/runs/987654321",
                }
            ]
            return CommandResult(returncode=0, stdout=json.dumps(payload))
        if cmd[:3] == ["gh", "run", "download"]:
            dir_idx = cmd.index("--dir") + 1
            dest = Path(cmd[dir_idx]) / "experiment-run-987654321-deadbeef"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_zip, dest / "experiment-run-987654321-deadbeef.zip")
            return CommandResult(returncode=0)
        return CommandResult(returncode=1, stderr=f"unexpected command: {cmd}")

    client = GitHubRunClient(
        repo="Archont561/geoai-mcp-eval",
        cache_dir=tmp_path / "cache",
        runner=fake_runner,
    )

    runs_list = client.list_runs(limit=5, branch="main")
    assert len(runs_list) == 1
    assert runs_list[0].database_id == 987654321

    # First load_latest downloads via gh; second load_run hits disk cache without calling gh
    with client.load_latest(branch="main") as ds1:
        assert len(ds1.measurements_df()) == 6
    download_calls_before = sum(1 for c in calls if c[:3] == ["gh", "run", "download"])
    assert download_calls_before == 1

    with client.load_run(987654321) as ds2:
        assert len(ds2.measurements_df()) == 6
    download_calls_after = sum(1 for c in calls if c[:3] == ["gh", "run", "download"])
    assert download_calls_after == 1

    # cache="refresh" bypasses the cache
    client.download_run(987654321, cache="refresh")
    assert sum(1 for c in calls if c[:3] == ["gh", "run", "download"]) == 2

    # Offline load_zip works without invoking gh at all
    with client.load_zip(source_zip) as offline:
        assert offline.run.run_id == "pilot-001"
        with RunArchive.open(source_zip) as arc:
            wrapped = RunDataset.from_archive(arc)
            assert len(wrapped.measurements_df()) == 6


def test_github_run_client_errors(tmp_path: Path) -> None:
    def failing_runner(_argv: Sequence[str]) -> CommandResult:
        return CommandResult(returncode=1, stderr="auth required")

    client = GitHubRunClient(cache_dir=tmp_path / "cache", runner=failing_runner)
    with pytest.raises(GitHubRunError, match="auth required"):
        client.list_runs()

    def empty_runner(argv: Sequence[str]) -> CommandResult:
        if list(argv)[:3] == ["gh", "run", "list"]:
            return CommandResult(returncode=0, stdout="[]")
        return CommandResult(returncode=0, stdout="")

    empty_client = GitHubRunClient(cache_dir=tmp_path / "cache2", runner=empty_runner)
    with pytest.raises(GitHubRunError, match="no successful completed runs"):
        empty_client.load_latest()
    with pytest.raises(GitHubRunError, match="no experiment-run"):
        empty_client.download_run(111)
