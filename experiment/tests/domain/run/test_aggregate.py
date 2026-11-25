"""Unit tests for ``experiment.domain.run.aggregate``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run import (
    AssertionResult,
    BehavioralAnnotations,
    CostAndProcessMetrics,
    DeterminismAudit,
    EnvironmentPin,
    ExperimentRun,
    InstrumentAudit,
    ModelPin,
    RunMergeError,
    RunProvenance,
    TokenUsage,
    Treatment,
    TrialMeasurement,
    TrialRecord,
)


def test_experiment_run_merge_combines_parallel_fragments_deterministically(
    sample_trial: TrialRecord,
) -> None:
    t0 = datetime(2026, 11, 24, 19, 0, tzinfo=UTC)
    t1 = datetime(2026, 11, 24, 19, 1, tzinfo=UTC)
    t2 = datetime(2026, 11, 24, 19, 2, tzinfo=UTC)

    preflight = ExperimentRun(
        run_id="run-42",
        stage="pilot",
        created_at=t0,
        provenance=RunProvenance(
            environment=EnvironmentPin(repo_sha="abc123", python="3.13.18", ollama="0.32.0")
        ),
    )
    model_part = ExperimentRun(
        run_id="run-42",
        stage="pilot",
        created_at=t1,
        provenance=RunProvenance(
            model=ModelPin(
                backend_id="local",
                tag="qwen2.5:3b",
                digest="sha256:deadbeef",
                temperature=0.0,
                max_tokens=2048,
                smoke_response="OK",
            )
        ),
    )
    trial_a = sample_trial
    meas_a = TrialMeasurement.from_assertions(
        key=trial_a.key,
        assertions=[
            AssertionResult(
                assertion_id="touches", predicate="touches", tier="spatial", passed=True
            )
        ],
        determinism=DeterminismAudit(passes_executed=3, consistent=True, passed=True),
        economics=CostAndProcessMetrics(
            wall_seconds=4.5,
            llm_calls=2,
            tool_calls=1,
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        ),
    ).with_annotations(BehavioralAnnotations(trajectory_class="typed_only"))
    cell_a = ExperimentRun(
        run_id="run-42",
        stage="pilot",
        created_at=t2,
        trials={trial_a.trial_id: trial_a},
        measurements={meas_a.trial_id: meas_a},
    )
    key_b = sample_trial.key.model_copy(update={"paradigm": "codegen", "enforcement_level": "none"})
    trial_b = sample_trial.model_copy(
        update={
            "key": key_b,
            "treatment": Treatment(paradigm="codegen", enforcement_level="none"),
        }
    )
    cell_b = ExperimentRun(
        run_id="run-42",
        stage="pilot",
        created_at=t2,
        trials={trial_b.trial_id: trial_b},
    )

    merged = ExperimentRun.merge([cell_b, preflight, cell_a, model_part])
    assert merged.run_id == "run-42"
    assert merged.created_at == t0
    assert merged.provenance.environment.repo_sha == "abc123"
    assert merged.provenance.model is not None
    assert merged.provenance.model.digest == "sha256:deadbeef"
    assert list(merged.trials) == sorted([trial_a.trial_id, trial_b.trial_id])
    assert meas_a.trial_id in merged.measurements

    merged_again = ExperimentRun.merge([merged, cell_a])
    assert merged_again == merged

    reloaded = ExperimentRun.model_validate_json(merged.model_dump_json())
    assert reloaded == merged
    schema = ExperimentRun.model_json_schema()
    assert schema["title"] == "ExperimentRun"
    assert "trials" in schema["properties"]
    assert "measurements" in schema["properties"]


@given(reps=st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=6, unique=True))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_experiment_run_merge_is_order_independent_and_idempotent(
    sample_trial: TrialRecord, reps: list[int]
) -> None:
    fragments = []
    for rep in reps:
        trial = sample_trial.model_copy(
            update={"key": sample_trial.key.model_copy(update={"repetition": rep})}
        )
        fragments.append(
            ExperimentRun(run_id="run-prop", stage="pilot", trials={trial.trial_id: trial})
        )
    forward = ExperimentRun.merge(fragments)
    backward = ExperimentRun.merge(list(reversed(fragments)))
    assert forward == backward
    assert ExperimentRun.merge([forward, forward]) == forward
    assert len(forward.trials) == len(reps)


def test_experiment_run_merge_rejects_conflicts_and_never_imputes_missing(
    sample_trial: TrialRecord,
) -> None:
    trial_a = sample_trial
    trial_a_conflict = sample_trial.model_copy(update={"status": "error"})

    with pytest.raises(RunMergeError, match="at least one"):
        ExperimentRun.merge([])

    r1 = ExperimentRun(run_id="run-1", stage="pilot", trials={trial_a.trial_id: trial_a})
    r2 = ExperimentRun(run_id="run-2", stage="pilot")
    with pytest.raises(RunMergeError, match="run_id"):
        ExperimentRun.merge([r1, r2])

    r_stage = ExperimentRun(run_id="run-1", stage="smoke")
    with pytest.raises(RunMergeError, match="stage"):
        ExperimentRun.merge([r1, r_stage])

    r_conflict = ExperimentRun(
        run_id="run-1", stage="pilot", trials={trial_a_conflict.trial_id: trial_a_conflict}
    )
    with pytest.raises(RunMergeError, match="conflicting trial"):
        ExperimentRun.merge([r1, r_conflict])

    r_env1 = ExperimentRun(
        run_id="run-1",
        provenance=RunProvenance(environment=EnvironmentPin(repo_sha="aaa")),
    )
    r_env2 = ExperimentRun(
        run_id="run-1",
        provenance=RunProvenance(environment=EnvironmentPin(repo_sha="bbb")),
    )
    with pytest.raises(RunMergeError, match="conflicting environment"):
        ExperimentRun.merge([r_env1, r_env2])

    expected = [trial_a.trial_id, "analysis-de9im-001/codegen/none/rep-1"]
    audited = r1.with_audit(expected)
    assert audited.instrument_audit is not None
    assert audited.instrument_audit.complete is False
    assert audited.instrument_audit.missing_trials == ["analysis-de9im-001/codegen/none/rep-1"]
    assert list(audited.trials) == [trial_a.trial_id]


@given(
    expected=st.lists(
        st.text(alphabet="abc123", min_size=1, max_size=6), min_size=1, max_size=8, unique=True
    ),
    verdicts=st.lists(st.booleans(), min_size=1, max_size=8),
)
def test_instrument_audit_complete_and_determinism_invariants(
    expected: list[str], verdicts: list[bool]
) -> None:
    verdict_map = dict(zip(expected, verdicts, strict=False))
    audit = InstrumentAudit.evaluate(
        expected=expected, logged=expected, determinism_verdicts=verdict_map
    )
    assert audit.complete is True
    assert audit.missing_trials == []
    assert audit.determinism_passed is all(verdict_map.values())


def test_experiment_run_index_validation_and_model_conflict(
    sample_trial: TrialRecord,
) -> None:
    assert sample_trial.all_cache_hits is False
    cached = sample_trial.model_copy(update={"cache_hits": 2, "cache_misses": 0})
    assert cached.all_cache_hits is True

    with pytest.raises(ValidationError, match="trial index key"):
        ExperimentRun(run_id="r", trials={"wrong/key": sample_trial})

    meas = TrialMeasurement.from_assertions(key=sample_trial.key, assertions=[])
    with pytest.raises(ValidationError, match="measurement index key"):
        ExperimentRun(run_id="r", measurements={"wrong/key": meas})

    r1 = ExperimentRun(run_id="r", provenance=RunProvenance(model=ModelPin(tag="a")))
    r2 = ExperimentRun(run_id="r", provenance=RunProvenance(model=ModelPin(tag="b")))
    with pytest.raises(RunMergeError, match="conflicting model pin"):
        ExperimentRun.merge([r1, r2])

    meas_conflict = TrialMeasurement.from_assertions(
        key=sample_trial.key,
        assertions=[AssertionResult(assertion_id="x", passed=True)],
    )
    m1 = ExperimentRun(run_id="r", measurements={meas.trial_id: meas})
    m2 = ExperimentRun(run_id="r", measurements={meas_conflict.trial_id: meas_conflict})
    with pytest.raises(RunMergeError, match="conflicting measurement"):
        ExperimentRun.merge([m1, m2])
