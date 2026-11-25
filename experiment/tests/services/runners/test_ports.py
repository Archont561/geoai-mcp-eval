"""Unit tests for ``experiment.services.runners.ports``."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from experiment.adapters import harness_io, task_repository
from experiment.services.runners.ports import CellRequest, RunSpec


def test_run_spec_and_cell_request_pydantic_validation(tmp_path: Path) -> None:
    spec = RunSpec(
        arms=("A", "B"),
        task_ids=("analysis-de9im-001",),
        driver="scripted",
        model="scripted",
        host="http://127.0.0.1:11434",
        repetitions=2,
    )
    assert RunSpec.model_validate_json(spec.model_dump_json()) == spec
    with pytest.raises(ValidationError):
        RunSpec(
            arms=("A",),
            task_ids=("analysis-de9im-001",),
            driver="scripted",
            model="scripted",
            host="http://127.0.0.1:11434",
            repetitions=0,
        )
    with pytest.raises(ValidationError):
        RunSpec(
            arms=("A",),
            task_ids=("analysis-de9im-001",),
            driver="scripted",
            model="scripted",
            host="http://127.0.0.1:11434",
            bogus=True,  # type: ignore[call-arg]
        )

    task_path = harness_io.TASK_ROOT / "analysis-de9im-001.yaml"
    req = CellRequest(
        task_path=task_path,
        task=task_repository.load_task(task_path),
        arm="A",
        driver="scripted",
        cell=tmp_path,
        model="scripted",
        host="http://127.0.0.1:11434",
        run_id="r1",
    )
    assert req.repetition == 1
    with pytest.raises(ValidationError):
        CellRequest(**{**req.model_dump(), "repetition": 0})
