"""Smoke tests for the package version and layered Clean Architecture entry points."""

from __future__ import annotations

import experiment
from experiment.adapters import backends, harness_io, task_repository, task_suite
from experiment.adapters.mcp import client as mcp_client
from experiment.domain import backend as backend_domain
from experiment.services import runners, runs, scoring


def test_package_imports() -> None:
    assert experiment.__version__ == "0.1.0"
    assert backends.BackendProfile is backend_domain.BackendProfile
    assert callable(task_repository.load_task)
    assert callable(task_suite.validate_suite)
    assert callable(mcp_client.list_tools)
    assert callable(runs.run_cell)
    assert callable(runs.run_experiment)
    assert callable(scoring.score_cell)
    assert callable(runners.ollama_arm_a)
    assert callable(runners.scripted_arm_a)
    assert runners.CellRequest is not None
    assert runners.HarnessPorts is not None
    assert callable(harness_io.run_python_sandboxed)
