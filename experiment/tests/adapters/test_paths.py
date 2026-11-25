"""Unit tests for ``experiment.adapters.paths``."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiment.adapters import paths
from experiment.adapters.task_repository import discover_task_ids


def test_paths_resolve_consistently_from_repo_and_custom_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXPERIMENT_CONFIG", raising=False)
    repo = paths.find_repo_root()
    assert (repo / "pyproject.toml").is_file()
    assert paths.tasks_root() == repo / "experiment" / "tasks"
    assert paths.results_root() == repo / "results"
    assert paths.config_path() == repo / "experiment.toml"
    assert paths.cache_root() == repo / ".cache" / "llm"
    assert paths.package_src_root() == repo / "experiment" / "src"

    assert paths.tasks_root(tmp_path) == tmp_path / "experiment" / "tasks"
    assert paths.results_root(tmp_path) == tmp_path / "results"
    assert paths.config_path(tmp_path) == tmp_path / "experiment.toml"
    assert paths.cache_root(tmp_path) == tmp_path / ".cache" / "llm"

    override = tmp_path / "custom.toml"
    monkeypatch.setenv("EXPERIMENT_CONFIG", str(override))
    assert paths.config_path() == override

    env = paths.experiment_env(tmp_path)
    assert str(tmp_path / "experiment" / "src") in env["PYTHONPATH"]
    assert str(tmp_path / "experiment-qgis-plugin") in env["PYTHONPATH"]

    ids = discover_task_ids(paths.tasks_root())
    assert set(ids) == {"analysis-de9im-001", "cartography-jenks-001", "prep-axis-order-001"}
