"""Unit tests for ``experiment_plugin._tasks``."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment_plugin import _tasks


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(content="valid", task_id="demo-task-001")
@given(
    content=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", max_size=25),
    task_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20),
)
def test_discover_and_find_task_yaml_handles_errors(
    tmp_path: Path, content: str, task_id: str
) -> None:
    (tmp_path / "broken.yaml").write_text("{not: [" + content, encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="parse errors"):
        _tasks.find_task_yaml(tmp_path, task_id)

    discovered = _tasks.discover_task_dir()
    assert discovered.parts[-2:] == ("experiment", "tasks")
    assert discovered.is_dir()


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(folder="nested")
@given(folder=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12))
def test_discovery_prefers_working_checkout_then_package_then_fallback(
    tmp_path: Path, folder: str
) -> None:
    cwd_repo = tmp_path / "cwd-repo"
    (cwd_repo / "experiment" / "tasks").mkdir(parents=True, exist_ok=True)
    nested = cwd_repo / folder
    nested.mkdir(exist_ok=True)
    pkg_repo = tmp_path / "pkg-repo"
    (pkg_repo / "experiment" / "tasks").mkdir(parents=True, exist_ok=True)
    fake_module = pkg_repo / "plugin" / "session.py"
    fake_module.parent.mkdir(parents=True, exist_ok=True)
    fake_module.write_text("", encoding="utf-8")
    assert (
        _tasks.discover_task_dir(cwd=nested, anchor=fake_module)
        == (cwd_repo / "experiment" / "tasks").resolve()
    )
    unrelated = tmp_path / "outside"
    unrelated.mkdir(exist_ok=True)
    assert (
        _tasks.discover_task_dir(cwd=unrelated, anchor=fake_module)
        == (pkg_repo / "experiment" / "tasks").resolve()
    )
    isolated = tmp_path / "zip-install" / "plugin" / "session.py"
    isolated.parent.mkdir(parents=True, exist_ok=True)
    isolated.write_text("", encoding="utf-8")
    assert (
        _tasks.discover_task_dir(cwd=unrelated, anchor=isolated)
        == (unrelated / "experiment" / "tasks").resolve()
    )
