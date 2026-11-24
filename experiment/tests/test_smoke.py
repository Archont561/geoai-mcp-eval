"""Smoke tests for the package version and the legacy runner imports."""

from __future__ import annotations

import experiment
from experiment import harness, prototype
from experiment.adapters import task_repository
from experiment.services import runs, scoring


def test_package_imports() -> None:
    assert experiment.__version__ == "0.1.0"
    public_names = {
        "CellRequest": harness.CellRequest,
        "RunSpec": harness.RunSpec,
        "discover_tasks": runs.discover_tasks,
        "load_task": task_repository.load_task,
        "score_cell": scoring.score_cell,
        "run_cell": runs.run_cell,
        "run_experiment": runs.run_experiment,
    }
    assert set(prototype.__all__) == set(public_names)
    for name, implementation in public_names.items():
        assert getattr(prototype, name) is implementation
