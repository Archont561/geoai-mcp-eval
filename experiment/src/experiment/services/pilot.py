"""Service boundary for pilot task suite validation and determinism checks."""

from __future__ import annotations

from pathlib import Path

from experiment.adapters.paths import tasks_root
from experiment.adapters.task_repository import TaskNotFoundError, find_task_file
from experiment.oracle import run_determinism_gate
from experiment.task_suite import validate_suite

__all__ = [
    "TaskNotFoundError",
    "default_task_root",
    "find_task_file",
    "run_determinism_gate",
    "validate_suite",
]


def default_task_root() -> Path:
    """Default absolute path to the committed pilot task suite."""
    return tasks_root()
