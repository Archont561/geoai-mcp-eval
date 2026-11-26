"""Path resolution properties for arbitrary checkout roots."""

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters import paths
from experiment.adapters.task_repository import discover_task_ids


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    root_name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=20)
)
def test_paths_resolve_consistently_from_repo_and_custom_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_name: str
) -> None:
    monkeypatch.delenv("EXPERIMENT_CONFIG", raising=False)
    repo = paths.find_repo_root()
    assert (repo / "pyproject.toml").is_file()
    assert paths.tasks_root() == repo / "experiment" / "tasks"
    assert paths.results_root() == repo / "results"
    assert paths.config_path() == repo / "experiment.toml"
    assert paths.cache_root() == repo / ".cache" / "llm"
    assert paths.package_src_root() == repo / "experiment" / "src"

    root = tmp_path / root_name
    assert paths.tasks_root(root) == root / "experiment" / "tasks"
    assert paths.results_root(root) == root / "results"
    assert paths.config_path(root) == root / "experiment.toml"
    assert paths.cache_root(root) == root / ".cache" / "llm"

    override = root / "custom.toml"
    monkeypatch.setenv("EXPERIMENT_CONFIG", str(override))
    assert paths.config_path() == override

    env = paths.experiment_env(root)
    assert str(root / "experiment" / "src") in env["PYTHONPATH"]
    assert str(root / "experiment-qgis-plugin") in env["PYTHONPATH"]
    assert set(discover_task_ids(paths.tasks_root())) == {
        "analysis-de9im-001",
        "cartography-jenks-001",
        "prep-axis-order-001",
    }
