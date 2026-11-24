"""Pinned runtime environment and model provenance models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from experiment.domain.run._common import STRICT_MODEL


class EnvironmentPin(BaseModel):
    """Software and repository versions pinned once per experiment run."""

    model_config = STRICT_MODEL

    repo_sha: str | None = None
    pixi_lock_sha256: str | None = None
    python: str | None = None
    qgis: str | None = None
    gdal: str | None = None
    geos: str | None = None
    proj: str | None = None
    ollama: str | None = None


class ModelPin(BaseModel):
    """Pinned LLM backend, tag, digest, decoding settings, and smoke probe."""

    model_config = STRICT_MODEL

    backend_id: str | None = None
    tag: str = Field(min_length=1)
    digest: str | None = None
    temperature: float | None = Field(default=None, ge=0.0)
    max_tokens: int | None = Field(default=None, ge=1)
    smoke_response: str | None = None
    smoke_raw: dict[str, Any] | None = None


class RunProvenance(BaseModel):
    """Complete execution context for one experiment run."""

    model_config = STRICT_MODEL

    environment: EnvironmentPin = Field(default_factory=EnvironmentPin)
    model: ModelPin | None = None
