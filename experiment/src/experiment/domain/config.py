"""Pure Pydantic v2 project configuration schema for ``experiment.toml`` (GEO-025).

No ``os``, ``pathlib``, ``tomllib``, or ``pydantic_settings`` imports live here:
loading files and merging ``EXPERIMENT_*`` environment variables belongs strictly
to :mod:`experiment.adapters.config`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from experiment.domain.backend import LOCAL_BACKEND, BackendProfile
from experiment.domain.run import Arm, Driver, EnforcementLevel, RunStage

_STRICT_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ExperimentDefaults(BaseModel):
    """Default execution knobs for ``experiment run`` and workflow commands."""

    model_config = _STRICT_CONFIG

    default_backend: str = Field(default=LOCAL_BACKEND, min_length=1)
    default_driver: Driver = Driver.SCRIPTED
    default_stage: RunStage = RunStage.PILOT
    default_arms: tuple[Arm, ...] = (Arm.A, Arm.B)
    default_repetitions: int = Field(default=1, ge=1)
    default_enforce: EnforcementLevel = EnforcementLevel.SEMANTIC_REPAIR
    use_llm_cache: bool = True


class PathsConfig(BaseModel):
    """Repository-relative string paths (resolved to ``Path`` inside ``adapters/paths.py``)."""

    model_config = _STRICT_CONFIG

    tasks_dir: str = Field(default="experiment/tasks", min_length=1)
    results_dir: str = Field(default="results", min_length=1)
    cache_dir: str = Field(default=".cache/llm", min_length=1)


class RunnerConfig(BaseModel):
    """Per-trial execution guardrails for LLM and sandbox runners."""

    model_config = _STRICT_CONFIG

    max_turns: int = Field(default=6, ge=1)
    max_cell_tokens: int | None = Field(default=None, ge=1)
    script_timeout_s: int = Field(default=60, ge=1)
    mcp_timeout_s: int = Field(default=60, ge=1)


class BackendCheckDefaults(BaseModel):
    """Default polling and tiny-completion bounds for ``experiment env backend-check``."""

    model_config = _STRICT_CONFIG

    poll_timeout_s: float = Field(default=30.0, ge=0.0)
    poll_interval_s: float = Field(default=1.0, ge=0.0)
    smoke_max_tokens: int = Field(default=16, ge=1)


class SshDefaults(BaseModel):
    """Non-secret SSH tunnel bind defaults (never keys or passwords)."""

    model_config = _STRICT_CONFIG

    remote_bind_host: str = Field(default="127.0.0.1", min_length=1)
    remote_bind_port: int = Field(default=11434, ge=1, le=65535)
    local_bind_host: str = Field(default="127.0.0.1", min_length=1)
    connect_timeout_s: float = Field(default=10.0, gt=0.0)

    @property
    def remote_bind_address(self) -> tuple[str, int]:
        """Return ``(remote_bind_host, remote_bind_port)`` for ``sshtunnel``."""
        return (self.remote_bind_host, self.remote_bind_port)


class ArchiveDefaults(BaseModel):
    """Default packing and CI-pruning flags for ``experiment archive``."""

    model_config = _STRICT_CONFIG

    fail_on_missing: bool = True
    skip_oracle: bool = False
    keep_artifact: str = ""


class QgisDefaults(BaseModel):
    """Default PyQGIS sandbox execution parameters."""

    model_config = _STRICT_CONFIG

    timeout_s: int = Field(default=120, ge=1)
    headless: bool = True


class ExperimentConfig(BaseModel):
    """Root validated project configuration loaded from ``experiment.toml``."""

    model_config = _STRICT_CONFIG

    experiment: ExperimentDefaults = Field(default_factory=ExperimentDefaults)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    backend_check: BackendCheckDefaults = Field(default_factory=BackendCheckDefaults)
    ssh: SshDefaults = Field(default_factory=SshDefaults)
    archive: ArchiveDefaults = Field(default_factory=ArchiveDefaults)
    qgis: QgisDefaults = Field(default_factory=QgisDefaults)
    backends: dict[str, BackendProfile] = Field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot containing zero secret values."""
        return self.model_dump(mode="json")
