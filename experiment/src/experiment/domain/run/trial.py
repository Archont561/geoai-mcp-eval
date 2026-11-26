"""Immutable treatment, trial identity, artifact pointer, and execution header models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from experiment.domain.run._common import (
    STRICT_MODEL,
    ArtifactKind,
    EnforcementLevel,
    ExecutionStatus,
    Paradigm,
)


class Treatment(BaseModel):
    """Approach and enforcement settings applied to a task, independent of the task."""

    model_config = STRICT_MODEL

    paradigm: Paradigm
    enforcement_level: EnforcementLevel = EnforcementLevel.NONE
    catalogue_hash: str | None = None

    @model_validator(mode="after")
    def _validate_enforcement(self) -> Treatment:
        if (
            not self.paradigm.allows_enforcement()
            and self.enforcement_level != EnforcementLevel.NONE
        ):
            raise ValueError(
                f"enforcement_level must be 'none' for paradigm {self.paradigm!r}, "
                f"got {self.enforcement_level!r}"
            )
        return self


class TrialKey(BaseModel):
    """Identify one trial: a condition (task and treatment) plus repetition."""

    model_config = STRICT_MODEL

    task_id: str = Field(min_length=1)
    paradigm: Paradigm
    enforcement_level: EnforcementLevel = EnforcementLevel.NONE
    repetition: int = Field(default=1, ge=1)

    @property
    def slug(self) -> str:
        """Canonical deterministic identifier for indexing trials and archive paths."""
        return f"{self.task_id}/{self.paradigm}/{self.enforcement_level}/rep-{self.repetition}"


class ArtifactRef(BaseModel):
    """Integrity pointer to a raw evidence or deliverable file inside a run archive."""

    model_config = STRICT_MODEL

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    kind: ArtifactKind = ArtifactKind.OTHER
    media_type: str | None = None

    @field_validator("path")
    @classmethod
    def _validate_relative_posix_path(cls, value: str) -> str:
        segments = value.split("/")
        invalid_segment = any(seg in ("", ".", "..") for seg in segments)
        if value.startswith("/") or "\\" in value or invalid_segment:
            raise ValueError(f"artifact path must be a safe relative POSIX path, got {value!r}")
        return value


class TranscriptEntry(BaseModel):
    """One structured record in a lazily loaded trial transcript."""

    model_config = STRICT_MODEL

    role: str = Field(min_length=1)
    content: str | None = None
    event: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_name: str | None = None
    returncode: int | None = None
    cache_hit: bool | None = None
    usage: dict[str, Any] | None = None
    usage_warning: str | None = None
    timestamp: datetime | None = None
    extra_fields: dict[str, Any] = Field(default_factory=dict)


class TrialRecord(BaseModel):
    """Immutable raw execution header for one trial (heavy payloads live behind ArtifactRefs)."""

    model_config = STRICT_MODEL

    key: TrialKey
    treatment: Treatment
    driver: str = Field(min_length=1)
    model_tag: str | None = None
    model_digest: str | None = None
    task_sha256: str | None = None
    fixture_sha256: str | None = None
    status: ExecutionStatus
    error: str | None = None
    abort_reason: str | None = None
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    artifacts: list[ArtifactRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_key_matches_treatment(self) -> TrialRecord:
        if (
            self.key.paradigm != self.treatment.paradigm
            or self.key.enforcement_level != self.treatment.enforcement_level
        ):
            raise ValueError("trial key and treatment must agree on paradigm and enforcement_level")
        return self

    @property
    def trial_id(self) -> str:
        return self.key.slug

    @property
    def all_cache_hits(self) -> bool:
        return self.cache_hits > 0 and self.cache_misses == 0
