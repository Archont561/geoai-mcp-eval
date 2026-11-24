"""Unified English ontology Pydantic models for experiment runs and measurements."""

from __future__ import annotations

from experiment.domain.run._common import (
    STRICT_MODEL,
    ArtifactKind,
    AssertionTier,
    EnforcementLevel,
    ExecutionStatus,
    FailureClass,
    Paradigm,
    RunStage,
    TrajectoryClass,
    arm_to_paradigm,
    enforce_code_to_level,
)
from experiment.domain.run.aggregate import ExperimentRun, InstrumentAudit, RunMergeError
from experiment.domain.run.measurement import (
    AssertionResult,
    BehavioralAnnotations,
    CostAndProcessMetrics,
    DeterminismAudit,
    OutcomeMetrics,
    TokenUsage,
    TrialMeasurement,
    compute_outcome_metrics,
)
from experiment.domain.run.provenance import EnvironmentPin, ModelPin, RunProvenance
from experiment.domain.run.trial import (
    ArtifactRef,
    TranscriptEntry,
    Treatment,
    TrialKey,
    TrialRecord,
)

__all__ = [
    "STRICT_MODEL",
    "ArtifactKind",
    "ArtifactRef",
    "AssertionResult",
    "AssertionTier",
    "BehavioralAnnotations",
    "CostAndProcessMetrics",
    "DeterminismAudit",
    "EnforcementLevel",
    "EnvironmentPin",
    "ExecutionStatus",
    "ExperimentRun",
    "FailureClass",
    "InstrumentAudit",
    "ModelPin",
    "OutcomeMetrics",
    "Paradigm",
    "RunMergeError",
    "RunProvenance",
    "RunStage",
    "TokenUsage",
    "TrajectoryClass",
    "TranscriptEntry",
    "Treatment",
    "TrialKey",
    "TrialMeasurement",
    "TrialRecord",
    "arm_to_paradigm",
    "compute_outcome_metrics",
    "enforce_code_to_level",
]
