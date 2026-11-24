"""Service boundary for pilot task suite validation and determinism checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiment import oracle, task_suite
from experiment.adapters import paths, task_repository

TaskNotFoundError = task_repository.TaskNotFoundError


def default_task_root() -> Path:
    """Default absolute path to the committed pilot task suite."""
    return paths.tasks_root()


def find_task_file(root: Path, task_id: str) -> Path:
    """Locate the task YAML carrying ``task_id`` under ``root``."""
    return task_repository.find_task_file(root, task_id)


def validate_suite(root: Path) -> Any:
    """Validate task schemas, fixtures, oracle types, and required trap coverage."""
    return task_suite.validate_suite(root)


def run_determinism_gate(task_path: Path, artifacts_dir: Path) -> Any:
    """Run the task oracle three times against fixed artifacts."""
    return oracle.run_determinism_gate(task_path, artifacts_dir)
