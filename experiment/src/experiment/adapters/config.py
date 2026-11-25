"""Unified ``experiment.toml`` + ``EXPERIMENT_*`` loader backed by ``pydantic-settings``.

Precedence (highest to lowest):
  1. Explicit programmatic / CLI overrides (``overrides=...``)
  2. ``EXPERIMENT_*`` environment variables (nested ``__`` delimiter + flat aliases)
  3. ``experiment.toml`` (via ``TomlConfigSettingsSource``)
  4. Pure Pydantic v2 model defaults in :class:`experiment.domain.config.ExperimentConfig`
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from experiment.adapters.paths import config_path, find_repo_root
from experiment.domain.backend import BackendError, BackendProfile
from experiment.domain.config import (
    ArchiveDefaults,
    BackendCheckDefaults,
    ExperimentConfig,
    ExperimentDefaults,
    PathsConfig,
    QgisDefaults,
    RunnerConfig,
    SshDefaults,
)

CONFIG_ENV_VAR = "EXPERIMENT_CONFIG"

_FLAT_ENV_MAP: tuple[tuple[str, str, str], ...] = (
    ("EXPERIMENT_BACKEND", "experiment", "default_backend"),
    ("EXPERIMENT_DRIVER", "experiment", "default_driver"),
    ("EXPERIMENT_STAGE", "experiment", "default_stage"),
    ("EXPERIMENT_REPETITIONS", "experiment", "default_repetitions"),
    ("EXPERIMENT_ENFORCE", "experiment", "default_enforce"),
    ("EXPERIMENT_USE_LLM_CACHE", "experiment", "use_llm_cache"),
    ("EXPERIMENT_POLL_TIMEOUT_S", "backend_check", "poll_timeout_s"),
    ("EXPERIMENT_POLL_INTERVAL_S", "backend_check", "poll_interval_s"),
    ("EXPERIMENT_FAIL_ON_MISSING", "archive", "fail_on_missing"),
    ("EXPERIMENT_SKIP_ORACLE", "archive", "skip_oracle"),
    ("EXPERIMENT_KEEP_ARTIFACT", "archive", "keep_artifact"),
)


class ConfigError(BackendError):
    """Raised when ``experiment.toml`` or environment overrides fail validation."""

    def __init__(self, detail: str) -> None:
        super().__init__("config", detail)


class ResolvedConfigPaths(BaseModel):
    """Absolute filesystem paths derived from :class:`PathsConfig`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tasks_dir: Path
    results_dir: Path
    cache_dir: Path


class _FlatEnvSource(PydanticBaseSettingsSource):
    """Translate flat ``EXPERIMENT_*`` env vars into nested section dicts."""

    def __init__(self, settings_cls: type[BaseSettings], env_map: Mapping[str, str]) -> None:
        super().__init__(settings_cls)
        self._env = env_map

    def get_field_value(self, _field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        nested: dict[str, Any] = {}
        for env_key, section, field_name in _FLAT_ENV_MAP:
            raw = self._env.get(env_key)
            if raw is not None and raw.strip() != "":
                nested.setdefault(section, {})[field_name] = raw.strip()
        return nested


class _CustomNestedEnvSource(PydanticBaseSettingsSource):
    """Read ``EXPERIMENT_<SECTION>__<KEY>`` from an injected ``env`` mapping."""

    def __init__(self, settings_cls: type[BaseSettings], env_map: Mapping[str, str]) -> None:
        super().__init__(settings_cls)
        self._env = env_map

    def get_field_value(self, _field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        prefix = "EXPERIMENT_"
        for raw_key, value in self._env.items():
            if not raw_key.startswith(prefix) or "__" not in raw_key[len(prefix) :]:
                continue
            parts = raw_key[len(prefix) :].lower().split("__")
            cursor = result
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[parts[-1]] = value
        return result


class _BaseExperimentSettings(BaseSettings):
    """``pydantic-settings`` container mirroring :class:`ExperimentConfig`."""

    model_config = SettingsConfigDict(
        env_prefix="EXPERIMENT_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    _toml_file: ClassVar[Path | None] = None
    _env_map: ClassVar[Mapping[str, str] | None] = None

    experiment: ExperimentDefaults = Field(default_factory=ExperimentDefaults)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    backend_check: BackendCheckDefaults = Field(default_factory=BackendCheckDefaults)
    ssh: SshDefaults = Field(default_factory=SshDefaults)
    archive: ArchiveDefaults = Field(default_factory=ArchiveDefaults)
    qgis: QgisDefaults = Field(default_factory=QgisDefaults)
    backends: dict[str, BackendProfile] = Field(default_factory=dict)

    @classmethod
    def settings_customise_sources(  # noqa: CC102
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del dotenv_settings, file_secret_settings
        env_map = cls._env_map
        active_env = os.environ if env_map is None else env_map
        nested_source = (
            env_settings if env_map is None else _CustomNestedEnvSource(settings_cls, env_map)
        )
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            nested_source,
            _FlatEnvSource(settings_cls, active_env),
        ]
        if cls._toml_file is not None:
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=cls._toml_file))
        return tuple(sources)


def _build_settings_cls(
    toml_file: Path | None,
    env_map: Mapping[str, str] | None,
) -> type[BaseSettings]:
    """Bind ``toml_file`` and ``env_map`` onto a fresh settings subclass."""
    return type(
        "_BoundExperimentSettings",
        (_BaseExperimentSettings,),
        {"_toml_file": toml_file, "_env_map": env_map},
    )


def _resolve_toml_file(
    path: Path | None,
    env: Mapping[str, str] | None,
) -> Path | None:
    """Resolve explicit path / ``EXPERIMENT_CONFIG`` / default ``experiment.toml``."""
    active_env = os.environ if env is None else env
    if path is not None:
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    env_path = active_env.get(CONFIG_ENV_VAR, "").strip()
    if env_path:
        explicit = Path(env_path).expanduser()
        if not explicit.is_file():
            raise ConfigError(f"config file from {CONFIG_ENV_VAR} not found: {explicit}")
        return explicit
    default = config_path()
    return default if default.is_file() else None


def load_config(
    path: Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ExperimentConfig:
    """Load and validate :class:`ExperimentConfig` honoring CLI > env > TOML > defaults."""
    toml_file = _resolve_toml_file(path, env)
    settings_cls = _build_settings_cls(toml_file, env)
    init_kwargs = dict(overrides or {})
    try:
        loaded = settings_cls(**init_kwargs)
    except (tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        source_label = str(toml_file) if toml_file is not None else "experiment configuration"
        raise ConfigError(f"{source_label}: {exc}") from exc
    return ExperimentConfig.model_validate(loaded.model_dump(mode="python"))


def resolve_config_paths(
    config: ExperimentConfig,
    repo: Path | None = None,
) -> ResolvedConfigPaths:
    """Resolve relative ``config.paths`` entries against ``repo`` (or repository root)."""
    root = repo or find_repo_root()
    return ResolvedConfigPaths(
        tasks_dir=(root / config.paths.tasks_dir).resolve(),
        results_dir=(root / config.paths.results_dir).resolve(),
        cache_dir=(root / config.paths.cache_dir).resolve(),
    )
