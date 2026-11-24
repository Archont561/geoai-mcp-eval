"""ExperimentRun aggregate root, InstrumentAudit, and deterministic fan-in merging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from experiment.domain.run._common import STRICT_MODEL, RunStage
from experiment.domain.run.measurement import TrialMeasurement
from experiment.domain.run.provenance import EnvironmentPin, ModelPin, RunProvenance
from experiment.domain.run.trial import TrialRecord


class RunMergeError(ValueError):
    """Raised when partial ExperimentRun fragments cannot be merged without conflict."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _merge_environment(pins: Sequence[EnvironmentPin]) -> EnvironmentPin:
    merged: dict[str, str | None] = {}
    for field_name in EnvironmentPin.model_fields:
        values = {getattr(pin, field_name) for pin in pins if getattr(pin, field_name) is not None}
        if len(values) > 1:
            raise RunMergeError(f"conflicting environment pin for {field_name!r}: {sorted(values)}")
        merged[field_name] = next(iter(values), None)
    return EnvironmentPin(**merged)


def _merge_model_pin(pins: Sequence[ModelPin | None]) -> ModelPin | None:
    present = [pin for pin in pins if pin is not None]
    if not present:
        return None
    first = present[0]
    for other in present[1:]:
        if other != first:
            raise RunMergeError("conflicting model pin across run fragments")
    return first


def _merge_mapping[RecordT](
    maps: Sequence[Mapping[str, RecordT]],
    *,
    label: str,
) -> dict[str, RecordT]:
    combined: dict[str, RecordT] = {}
    for mapping in maps:
        for key, value in mapping.items():
            if key in combined and combined[key] != value:
                raise RunMergeError(f"conflicting {label} for key {key!r}")
            combined[key] = value
    return {key: combined[key] for key in sorted(combined)}


class InstrumentAudit(BaseModel):
    """Completeness and determinism audit over all trials in a run."""

    model_config = STRICT_MODEL

    expected_trials: list[str] = Field(default_factory=list)
    logged_trials: list[str] = Field(default_factory=list)
    missing_trials: list[str] = Field(default_factory=list)
    extra_trials: list[str] = Field(default_factory=list)
    complete: bool = False
    determinism_passed: bool | None = None
    audited_at: datetime | None = None

    @classmethod
    def evaluate(
        cls,
        *,
        expected: Sequence[str],
        logged: Sequence[str],
        determinism_verdicts: Mapping[str, bool] | None = None,
        audited_at: datetime | None = None,
    ) -> InstrumentAudit:
        """Compute completeness and determinism audit without imputing missing trials."""
        expected_set = set(expected)
        logged_set = set(logged)
        missing = sorted(expected_set - logged_set)
        extra = sorted(logged_set - expected_set)
        det_ok: bool | None = None
        if determinism_verdicts:
            det_ok = all(determinism_verdicts.values())
        return cls(
            expected_trials=sorted(expected_set),
            logged_trials=sorted(logged_set),
            missing_trials=missing,
            extra_trials=extra,
            complete=not missing,
            determinism_passed=det_ok,
            audited_at=audited_at or _utc_now(),
        )


class ExperimentRun(BaseModel):
    """Canonical single-run aggregate root uniting provenance, trials, measurements, and audit."""

    model_config = STRICT_MODEL

    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    stage: RunStage = "pilot"
    created_at: datetime = Field(default_factory=_utc_now)
    provenance: RunProvenance = Field(default_factory=RunProvenance)
    trials: dict[str, TrialRecord] = Field(default_factory=dict)
    measurements: dict[str, TrialMeasurement] = Field(default_factory=dict)
    instrument_audit: InstrumentAudit | None = None

    @model_validator(mode="after")
    def _validate_index_consistency(self) -> ExperimentRun:
        for tid, trial in self.trials.items():
            if tid != trial.trial_id:
                raise ValueError(f"trial index key {tid!r} does not match {trial.trial_id!r}")
        for tid, measurement in self.measurements.items():
            if tid != measurement.trial_id:
                raise ValueError(
                    f"measurement index key {tid!r} does not match {measurement.trial_id!r}"
                )
            if tid in self.trials and self.trials[tid].key != measurement.key:
                raise ValueError(f"measurement key disagrees with trial key for {tid!r}")
        return self

    @classmethod
    def merge(cls, parts: Sequence[ExperimentRun]) -> ExperimentRun:
        """Deterministically merge partial run fragments; reject conflicts, never impute."""
        if not parts:
            raise RunMergeError("ExperimentRun.merge requires at least one fragment")
        run_ids = {part.run_id for part in parts}
        if len(run_ids) > 1:
            raise RunMergeError(f"cannot merge fragments with differing run_id: {sorted(run_ids)}")
        stages = {part.stage for part in parts}
        if len(stages) > 1:
            raise RunMergeError(f"cannot merge fragments with differing stage: {sorted(stages)}")
        audits = [part.instrument_audit for part in parts if part.instrument_audit is not None]
        environment = _merge_environment([part.provenance.environment for part in parts])
        model_pin = _merge_model_pin([part.provenance.model for part in parts])
        provenance = RunProvenance(environment=environment, model=model_pin)
        trials = _merge_mapping([part.trials for part in parts], label="trial")
        measurements = _merge_mapping([part.measurements for part in parts], label="measurement")
        earliest = min(part.created_at for part in parts)
        return cls(
            run_id=parts[0].run_id,
            stage=parts[0].stage,
            created_at=earliest,
            provenance=provenance,
            trials=trials,
            measurements=measurements,
            instrument_audit=audits[-1] if audits else None,
        )

    def with_audit(
        self,
        expected_trials: Sequence[str],
        *,
        audited_at: datetime | None = None,
    ) -> ExperimentRun:
        """Return a copy carrying a freshly evaluated InstrumentAudit."""
        det_verdicts = {
            tid: m.determinism.passed
            for tid, m in self.measurements.items()
            if m.determinism is not None
        }
        audit = InstrumentAudit.evaluate(
            expected=expected_trials,
            logged=list(self.trials),
            determinism_verdicts=det_verdicts or None,
            audited_at=audited_at,
        )
        return self.model_copy(update={"instrument_audit": audit})
