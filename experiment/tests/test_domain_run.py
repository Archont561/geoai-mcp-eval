"""Tests for the unified English ontology domain models and TrialMeasurement DTO (GEO-014)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run import (
    ArtifactRef,
    AssertionResult,
    BehavioralAnnotations,
    CostAndProcessMetrics,
    DeterminismAudit,
    EnvironmentPin,
    ExperimentRun,
    InstrumentAudit,
    ModelPin,
    OutcomeMetrics,
    RunMergeError,
    RunProvenance,
    TokenUsage,
    TranscriptEntry,
    Treatment,
    TrialKey,
    TrialMeasurement,
    TrialRecord,
    arm_to_paradigm,
    enforce_code_to_level,
)
from experiment.domain.usage import UsageAccumulator, UsageSnapshot

VALID_SHA = "a" * 64
OTHER_SHA = "b" * 64


def _sample_trial(
    *,
    task_id: str = "analysis-de9im-001",
    paradigm: str = "typed_mcp",
    enforcement: str = "semantic_repair",
    rep: int = 1,
    status: str = "ok",
) -> TrialRecord:
    key = TrialKey(
        task_id=task_id,
        paradigm=paradigm,  # type: ignore[arg-type]
        enforcement_level=enforcement,  # type: ignore[arg-type]
        repetition=rep,
    )
    treatment = Treatment(
        paradigm=paradigm,  # type: ignore[arg-type]
        enforcement_level=enforcement,  # type: ignore[arg-type]
        catalogue_hash=VALID_SHA if paradigm == "typed_mcp" else None,
    )
    return TrialRecord(
        key=key,
        treatment=treatment,
        driver="ollama",
        model_tag="qwen2.5:3b",
        model_digest="sha256:abc",
        status=status,  # type: ignore[arg-type]
        artifacts=[
            ArtifactRef(
                path="result.json",
                sha256=VALID_SHA,
                bytes=128,
                kind="deliverable",
                media_type="application/json",
            )
        ],
    )


def test_legacy_mappers_translate_arms_and_enforcement_levels() -> None:
    assert arm_to_paradigm("A") == "typed_mcp"
    assert arm_to_paradigm("B") == "codegen"
    assert arm_to_paradigm("C") == "hybrid_mcp_code"
    assert arm_to_paradigm("D") == "code_driving_mcp"
    assert arm_to_paradigm("H") == "human_gui"
    assert enforce_code_to_level("N0") == "none"
    assert enforce_code_to_level("N1") == "declarative"
    assert enforce_code_to_level("N2") == "syntactic"
    assert enforce_code_to_level("N3") == "semantic_repair"
    assert enforce_code_to_level("N4") == "transactional"
    with pytest.raises(ValueError, match="unknown arm"):
        arm_to_paradigm("Z")
    with pytest.raises(ValueError, match="unknown enforcement"):
        enforce_code_to_level("N9")


def test_treatment_rejects_enforcement_on_codegen_and_human_gui() -> None:
    Treatment(paradigm="codegen", enforcement_level="none")
    Treatment(paradigm="human_gui", enforcement_level="none")
    Treatment(paradigm="typed_mcp", enforcement_level="semantic_repair")

    with pytest.raises(ValidationError, match="enforcement_level must be 'none'"):
        Treatment(paradigm="codegen", enforcement_level="syntactic")
    with pytest.raises(ValidationError, match="enforcement_level must be 'none'"):
        Treatment(paradigm="human_gui", enforcement_level="declarative")


def test_trial_record_validates_key_matches_treatment_and_safe_artifact_paths() -> None:
    key = TrialKey(
        task_id="analysis-de9im-001",
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        repetition=1,
    )
    mismatch = Treatment(paradigm="codegen", enforcement_level="none")
    with pytest.raises(ValidationError, match="key and treatment must agree"):
        TrialRecord(key=key, treatment=mismatch, driver="ollama", status="ok")

    for bad_path in ("/etc/passwd", "../escape.json", "a/../../b", "dir\\file.json"):
        with pytest.raises(ValidationError, match="relative POSIX path"):
            ArtifactRef(path=bad_path, sha256=VALID_SHA, bytes=10)


def test_strict_extra_forbid_and_nullable_tokens_never_imputed() -> None:
    with pytest.raises(ValidationError):
        EnvironmentPin(repo_sha="deadbeef", unknown_key="nope")  # type: ignore[call-arg]

    tokens = TokenUsage(calls_missing_usage=2, warnings=["endpoint did not report token usage"])
    assert tokens.input_tokens is None
    assert tokens.output_tokens is None
    assert tokens.total_tokens is None
    assert tokens.calls_missing_usage == 2


def test_trial_measurement_from_assertions_computes_outcomes_and_silent_invalid() -> None:
    key = TrialKey(
        task_id="prep-axis-order-001",
        paradigm="codegen",
        enforcement_level="none",
        repetition=1,
    )
    # All pass -> task_success=True, predicate_score=1.0, silent_invalid=False
    all_pass = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="exists", predicate="file_exists", tier="trivial", passed=True
            ),
            AssertionResult(
                assertion_id="axis", predicate="point_axis_order", tier="spatial", passed=True
            ),
        ],
    )
    assert all_pass.outcomes == OutcomeMetrics(
        task_success=True, predicate_score=1.0, silent_invalid=False
    )

    # Trivial passes, spatial fails -> silent_invalid=True (RQ8)
    silent = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="exists", predicate="file_exists", tier="trivial", passed=True
            ),
            AssertionResult(
                assertion_id="count", predicate="feature_count", tier="trivial", passed=True
            ),
            AssertionResult(
                assertion_id="axis", predicate="point_axis_order", tier="spatial", passed=False
            ),
        ],
    )
    assert silent.outcomes.task_success is False
    assert silent.outcomes.predicate_score == pytest.approx(2 / 3)
    assert silent.outcomes.silent_invalid is True

    # Trivial fails too -> crash/missing deliverable, NOT silent_invalid
    crashed = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="exists", predicate="file_exists", tier="trivial", passed=False
            ),
            AssertionResult(
                assertion_id="axis", predicate="point_axis_order", tier="spatial", passed=False
            ),
        ],
    )
    assert crashed.outcomes.task_success is False
    assert crashed.outcomes.predicate_score == 0.0
    assert crashed.outcomes.silent_invalid is False

    # No assertions -> task_success=False, predicate_score=0.0, silent_invalid=False
    empty = TrialMeasurement.from_assertions(key=key, assertions=[])
    assert empty.outcomes == OutcomeMetrics(
        task_success=False, predicate_score=0.0, silent_invalid=False
    )


def test_experiment_run_merge_combines_parallel_fragments_deterministically() -> None:
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
    trial_a = _sample_trial(paradigm="typed_mcp", enforcement="semantic_repair", rep=1)
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
    trial_b = _sample_trial(paradigm="codegen", enforcement="none", rep=1)
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

    # Idempotent merge of identical fragment succeeds
    merged_again = ExperimentRun.merge([merged, cell_a])
    assert merged_again == merged

    # Round-trip JSON + self-describing JSON Schema export
    reloaded = ExperimentRun.model_validate_json(merged.model_dump_json())
    assert reloaded == merged
    schema = ExperimentRun.model_json_schema()
    assert schema["title"] == "ExperimentRun"
    assert "trials" in schema["properties"]
    assert "measurements" in schema["properties"]


def test_experiment_run_merge_rejects_conflicts_and_never_imputes_missing() -> None:
    trial_a = _sample_trial(status="ok")
    trial_a_conflict = _sample_trial(status="error")

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

    # Completeness audit records missing trials without inventing them
    expected = [trial_a.trial_id, "analysis-de9im-001/codegen/none/rep-1"]
    audited = r1.with_audit(expected)
    assert audited.instrument_audit is not None
    assert audited.instrument_audit.complete is False
    assert audited.instrument_audit.missing_trials == ["analysis-de9im-001/codegen/none/rep-1"]
    assert list(audited.trials) == [trial_a.trial_id]


def test_transcript_entry_and_instrument_audit_determinism_summary() -> None:
    entry = TranscriptEntry(role="assistant", content="done", cache_hit=False)
    assert entry.role == "assistant"
    audit = InstrumentAudit.evaluate(
        expected=["t1", "t2"],
        logged=["t1", "t2"],
        determinism_verdicts={"t1": True, "t2": False},
    )
    assert audit.complete is True
    assert audit.determinism_passed is False


def test_usage_accumulator_to_token_usage_preserves_nulls() -> None:
    acc = UsageAccumulator(max_cell_tokens=500)
    snapshot = UsageSnapshot(input_tokens=10, output_tokens=None, total_tokens=None, warning="part")
    acc.record(snapshot)
    dto = acc.to_token_usage()
    assert dto.input_tokens == 10
    assert dto.output_tokens is None
    assert dto.total_tokens is None
    assert dto.calls_missing_usage == 1
    assert dto.max_trial_tokens == 500
    assert dto.warnings == ["part"]


def test_experiment_run_index_validation_and_model_conflict() -> None:
    trial = _sample_trial()
    assert trial.all_cache_hits is False
    cached = trial.model_copy(update={"cache_hits": 2, "cache_misses": 0})
    assert cached.all_cache_hits is True

    with pytest.raises(ValidationError, match="trial index key"):
        ExperimentRun(run_id="r", trials={"wrong/key": trial})

    meas = TrialMeasurement.from_assertions(key=trial.key, assertions=[])
    with pytest.raises(ValidationError, match="measurement index key"):
        ExperimentRun(run_id="r", measurements={"wrong/key": meas})

    r1 = ExperimentRun(run_id="r", provenance=RunProvenance(model=ModelPin(tag="a")))
    r2 = ExperimentRun(run_id="r", provenance=RunProvenance(model=ModelPin(tag="b")))
    with pytest.raises(RunMergeError, match="conflicting model pin"):
        ExperimentRun.merge([r1, r2])

    meas_conflict = TrialMeasurement.from_assertions(
        key=trial.key,
        assertions=[AssertionResult(assertion_id="x", passed=True)],
    )
    m1 = ExperimentRun(run_id="r", measurements={meas.trial_id: meas})
    m2 = ExperimentRun(run_id="r", measurements={meas_conflict.trial_id: meas_conflict})
    with pytest.raises(RunMergeError, match="conflicting measurement"):
        ExperimentRun.merge([m1, m2])


@given(
    passes=st.lists(st.booleans(), min_size=1, max_size=12),
    tiers=st.lists(st.sampled_from(["trivial", "spatial", "value"]), min_size=1, max_size=12),
)
def test_outcome_metrics_properties(passes: list[bool], tiers: list[str]) -> None:
    n = min(len(passes), len(tiers))
    assertions = [
        AssertionResult(
            assertion_id=f"a-{idx}",
            predicate=f"pred_{idx}",
            tier=tiers[idx],  # type: ignore[arg-type]
            passed=passes[idx],
        )
        for idx in range(n)
    ]
    key = TrialKey(task_id="t", paradigm="codegen", enforcement_level="none", repetition=1)
    measurement = TrialMeasurement.from_assertions(key=key, assertions=assertions)
    assert measurement.outcomes.task_success is all(passes[:n])
    assert 0.0 <= measurement.outcomes.predicate_score <= 1.0
    if measurement.outcomes.task_success:
        assert measurement.outcomes.predicate_score == 1.0
        assert measurement.outcomes.silent_invalid is False
