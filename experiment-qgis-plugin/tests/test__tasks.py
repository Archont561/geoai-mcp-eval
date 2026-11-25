"""Unit tests for ``experiment_plugin._tasks``."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiment_plugin import _tasks


def test_discover_and_find_task_yaml_handles_errors(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("{not: [valid", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="parse errors"):
        _tasks.find_task_yaml(tmp_path, "demo-task-001")

    discovered = _tasks.discover_task_dir()
    assert discovered.parts[-2:] == ("experiment", "tasks")
    assert discovered.is_dir()
