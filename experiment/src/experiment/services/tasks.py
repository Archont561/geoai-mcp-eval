"""Service boundary for benchmark task discovery, inspection, and suite validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiment.adapters import paths, task_repository, task_suite
from experiment.domain.task import Task

TaskNotFoundError = task_repository.TaskNotFoundError


def default_task_root() -> Path:
    """Default absolute path to the committed benchmark task suite."""
    return paths.tasks_root()


def list_tasks(root: Path | None = None) -> list[Task]:
    """Load and return all validated tasks under ``root`` sorted by task ID."""
    suite_root = root if root is not None else default_task_root()
    task_files = task_repository.discover_task_files(suite_root)
    tasks = [task_repository.load_task(path) for path in task_files]
    return sorted(tasks, key=lambda task: task.id)


def get_task(task_id: str, root: Path | None = None) -> tuple[Path, Task]:
    """Locate and load one task by identifier, raising ``TaskNotFoundError`` if absent."""
    suite_root = root if root is not None else default_task_root()
    path = task_repository.find_task_file(suite_root, task_id)
    return path, task_repository.load_task(path)


def validate_suite(root: Path | None = None) -> Any:
    """Validate task schemas, fixtures, oracle types, and required trap coverage."""
    suite_root = root if root is not None else default_task_root()
    return task_suite.validate_suite(suite_root)
