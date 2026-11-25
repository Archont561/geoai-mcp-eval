"""Unit tests for ``experiment.services.tasks``."""

from __future__ import annotations

from experiment.services import tasks


def test_tasks_service_lists_loads_and_validates_shipped_suite() -> None:
    root = tasks.default_task_root()
    listed = tasks.list_tasks(root)
    assert len(listed) >= 3
    task_file, task = tasks.get_task("analysis-de9im-001", root)
    assert task_file.is_file()
    assert task.id == "analysis-de9im-001"
    report = tasks.validate_suite(root)
    assert report.passed is True
