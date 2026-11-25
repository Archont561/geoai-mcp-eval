"""Derived TrialMeasurement DTO: oracle verdicts, outcomes, economics, and annotations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from experiment.domain.run._common import (
    STRICT_MODEL,
    AssertionTier,
    FailureClass,
    TrajectoryClass,
)
from experiment.domain.run.trial import TrialKey


class TokenUsage(BaseModel):
    """Reported token accounting for one trial; missing values stay None, never imputed."""

    model_config = STRICT_MODEL

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    calls_with_usage: int = Field(default=0, ge=0)
    calls_missing_usage: int = Field(default=0, ge=0)
    max_trial_tokens: int | None = Field(default=None, ge=1)
    cap_exceeded: bool = False
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_summary_dict(cls, raw: Mapping[str, Any]) -> TokenUsage:
        """Build TokenUsage from a legacy UsageAccumulator.to_summary() mapping."""
        raw_warnings = raw.get("warnings") or ()
        warnings = [str(item) for item in raw_warnings]
        with_usage = int(raw.get("calls_with_usage", 0))
        missing_usage = int(raw.get("calls_missing_usage", 0))
        exceeded = bool(raw.get("cap_exceeded", False))
        return cls(
            input_tokens=raw.get("input_tokens"),
            output_tokens=raw.get("output_tokens"),
            total_tokens=raw.get("total_tokens"),
            calls_with_usage=with_usage,
            calls_missing_usage=missing_usage,
            max_trial_tokens=raw.get("max_cell_tokens"),
            cap_exceeded=exceeded,
            warnings=warnings,
        )


class AssertionResult(BaseModel):
    """Outcome of a single named oracle assertion against a trial's deliverable."""

    model_config = STRICT_MODEL

    assertion_id: str = Field(min_length=1)
    predicate: str | None = None
    tier: AssertionTier | None = None
    passed: bool
    detail: str = ""


class DeterminismAudit(BaseModel):
    """Multi-pass oracle determinism verification on fixed trial deliverables."""

    model_config = STRICT_MODEL

    passes_required: int = Field(default=3, ge=1)
    passes_executed: int = Field(ge=0)
    consistent: bool
    passed: bool
    issues: list[str] = Field(default_factory=list)


class OutcomeMetrics(BaseModel):
    """Primary binary and continuous effectiveness metrics derived from oracle assertions."""

    model_config = STRICT_MODEL

    task_success: bool
    predicate_score: float = Field(ge=0.0, le=1.0)
    silent_invalid: bool


class CostAndProcessMetrics(BaseModel):
    """Execution cost and process proxies (nullable when unmeasured, never fabricated)."""

    model_config = STRICT_MODEL

    wall_seconds: float | None = Field(default=None, ge=0.0)
    llm_calls: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
    repair_turns: int | None = Field(default=None, ge=0)
    schema_violations: int | None = Field(default=None, ge=0)
    human_steps: int | None = Field(default=None, ge=0)
    tokens: TokenUsage = Field(default_factory=TokenUsage)


class BehavioralAnnotations(BaseModel):
    """Optional descriptive/post-hoc trajectory and failure codings (never alter task_success)."""

    model_config = STRICT_MODEL

    trajectory_class: TrajectoryClass | None = None
    failure_class: FailureClass | None = None
    coder_id: str | None = None
    semantic_judge_notes: str | None = None


TIER_TRIVIAL: AssertionTier = "trivial"
TIER_SPATIAL: AssertionTier = "spatial"
TIER_VALUE: AssertionTier = "value"

_TIER_ALIASES: dict[str, AssertionTier] = {
    "a": TIER_TRIVIAL,
    "b": TIER_SPATIAL,
    "c": TIER_VALUE,
    "trivial": TIER_TRIVIAL,
    "spatial": TIER_SPATIAL,
    "value": TIER_VALUE,
}
_TYPE_TO_TIER: dict[str, AssertionTier] = {
    "file_exists": TIER_TRIVIAL,
    "ogr_readable": TIER_TRIVIAL,
    "feature_count": TIER_TRIVIAL,
    "geojson_feature_count": TIER_TRIVIAL,
    "raster_shape": TIER_TRIVIAL,
    "nodata_ok": TIER_TRIVIAL,
    "fields_present": TIER_TRIVIAL,
    "crs_equals": TIER_SPATIAL,
    "axis_order_ok": TIER_SPATIAL,
    "geom_type_in": TIER_SPATIAL,
    "geometry_valid": TIER_SPATIAL,
    "de9im_relation": TIER_SPATIAL,
    "representative_point_matches": TIER_SPATIAL,
    "extent_within_tol": TIER_SPATIAL,
    "buffer_distance": TIER_SPATIAL,
    "attr_stats": TIER_VALUE,
    "jenks_classification": TIER_VALUE,
    "min_dist_to": TIER_VALUE,
}


def infer_assertion_tier(
    assertion_type: str,
    explicit_tier: str | None = None,
) -> AssertionTier | None:
    """Resolve an assertion's English complexity tier from an explicit tag or type name."""
    if explicit_tier is not None:
        mapped = _TIER_ALIASES.get(explicit_tier.strip().lower())
        if mapped is not None:
            return mapped
    return _TYPE_TO_TIER.get(assertion_type.strip().lower())


def compute_outcome_metrics(
    assertions: Sequence[AssertionResult],
    *,
    deliverable_readable: bool | None = None,
) -> OutcomeMetrics:
    """Derive task_success, predicate_score, and silent_invalid from oracle assertions."""
    if not assertions:
        return OutcomeMetrics(task_success=False, predicate_score=0.0, silent_invalid=False)
    passed_count = sum(1 for item in assertions if item.passed)
    task_success = passed_count == len(assertions)
    predicate_score = passed_count / len(assertions)
    trivial = [item for item in assertions if item.tier == TIER_TRIVIAL]
    domain_checks = [item for item in assertions if item.tier in (TIER_SPATIAL, TIER_VALUE)]
    has_domain_failure = any(not item.passed for item in domain_checks)
    if trivial:
        deliverable_ok = all(item.passed for item in trivial) and deliverable_readable is not False
    else:
        deliverable_ok = deliverable_readable is True
    silent_invalid = deliverable_ok and has_domain_failure
    return OutcomeMetrics(
        task_success=task_success,
        predicate_score=predicate_score,
        silent_invalid=silent_invalid,
    )


@dataclass(frozen=True)
class MeasurementContext:
    """Optional contextual signals attached when constructing a :class:`TrialMeasurement`."""

    deliverable_readable: bool | None = None
    determinism: DeterminismAudit | None = None
    economics: CostAndProcessMetrics | None = None


class TrialMeasurement(BaseModel):
    """Derived Measurement DTO for one trial — shared across agent paradigms and human runs."""

    model_config = STRICT_MODEL

    trial_id: str = Field(min_length=1)
    key: TrialKey
    assertions: list[AssertionResult] = Field(default_factory=list)
    outcomes: OutcomeMetrics
    determinism: DeterminismAudit | None = None
    economics: CostAndProcessMetrics = Field(default_factory=CostAndProcessMetrics)
    annotations: BehavioralAnnotations = Field(default_factory=BehavioralAnnotations)

    @classmethod
    def from_assertions(
        cls,
        *,
        key: TrialKey,
        assertions: Sequence[AssertionResult],
        determinism: DeterminismAudit | None = None,
        economics: CostAndProcessMetrics | None = None,
    ) -> TrialMeasurement:
        """Build a TrialMeasurement DTO with OutcomeMetrics derived strictly from assertions."""
        return cls.build(
            key=key,
            assertions=assertions,
            context=MeasurementContext(determinism=determinism, economics=economics),
        )

    @classmethod
    def build(
        cls,
        *,
        key: TrialKey,
        assertions: Sequence[AssertionResult],
        context: MeasurementContext | None = None,
    ) -> TrialMeasurement:
        """Build a TrialMeasurement DTO with optional explicit deliverable readability signal."""
        ctx = context or MeasurementContext()
        assertion_list = list(assertions)
        outcomes = compute_outcome_metrics(
            assertion_list, deliverable_readable=ctx.deliverable_readable
        )
        return cls(
            trial_id=key.slug,
            key=key,
            assertions=assertion_list,
            outcomes=outcomes,
            determinism=ctx.determinism,
            economics=ctx.economics or CostAndProcessMetrics(),
        )

    def with_annotations(self, annotations: BehavioralAnnotations) -> TrialMeasurement:
        """Return a copy attaching post-hoc behavioral/failure annotations."""
        return self.model_copy(update={"annotations": annotations})
