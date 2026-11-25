"""Single source of truth for repository, package, task, and result paths."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT_MARKERS = ("tasknest.toml", "pixi.toml")


def package_src_root() -> Path:
    """Absolute path to ``experiment/src``."""
    return Path(__file__).resolve().parents[2]


def experiment_root() -> Path:
    """Absolute path to ``experiment/``."""
    return package_src_root().parent


def find_repo_root(cwd: Path | None = None) -> Path:
    """Locate the repository root regardless of whether cwd is root or ``experiment/``."""
    starts = (
        (cwd or Path.cwd()).resolve(),
        Path(__file__).resolve().parent,
    )
    for start in starts:
        for candidate in (start, *start.parents):
            if any((candidate / marker).is_file() for marker in _ROOT_MARKERS):
                return candidate
    return (cwd or Path.cwd()).resolve()


def tasks_root(repo: Path | None = None) -> Path:
    """Absolute path to ``experiment/tasks``."""
    if repo is not None:
        return repo / "experiment" / "tasks"
    return experiment_root() / "tasks"


def results_root(repo: Path | None = None) -> Path:
    """Absolute path to ``results``."""
    if repo is not None:
        return repo / "results"
    return experiment_root().parent / "results"


def config_path(repo: Path | None = None) -> Path:
    """Absolute path to ``experiment.toml`` (honoring ``EXPERIMENT_CONFIG`` when unset)."""
    if repo is not None:
        return repo / "experiment.toml"
    env_override = os.environ.get("EXPERIMENT_CONFIG", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return find_repo_root() / "experiment.toml"


def cache_root(repo: Path | None = None) -> Path:
    """Absolute path to ``.cache/llm``."""
    return (repo or find_repo_root()) / ".cache" / "llm"


def experiment_env(repo_root: Path | None = None) -> dict[str, str]:
    """Environment mapping with ``PYTHONPATH`` covering ``experiment/src`` and the plugin."""
    root = repo_root or find_repo_root()
    merged = os.environ.copy()
    src_roots = [
        root / "experiment" / "src",
        root / "experiment-qgis-plugin",
    ]
    merged["PYTHONPATH"] = os.pathsep.join(str(path) for path in src_roots)
    return merged
