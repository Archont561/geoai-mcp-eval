"""Service facade for loading and inspecting unified ``experiment.toml`` configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from experiment.adapters import config as config_adapter
from experiment.adapters.config import ConfigError
from experiment.domain.config import ExperimentConfig

__all__ = [
    "ConfigError",
    "ExperimentConfig",
    "get_config",
    "inspect_config",
]


def get_config(
    path: Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> ExperimentConfig:
    """Return validated :class:`ExperimentConfig` from ``path`` or root ``experiment.toml``."""
    return config_adapter.load_config(path, overrides=overrides)


def inspect_config(path: Path | None = None) -> dict[str, Any]:
    """Return a JSON-safe, secret-free snapshot of the effective experiment configuration."""
    return get_config(path).to_safe_dict()
