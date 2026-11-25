"""Unit tests for ``experiment.services.runners.ports``."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.runners.ports import CellRequest, RunSpec


@given(repetitions=st.integers(min_value=1, max_value=50))
def test_run_spec_roundtrips_positive_repetitions(repetitions: int) -> None:
    spec = RunSpec(
        arms=("A", "B"),
        task_ids=("analysis-de9im-001",),
        driver="scripted",
        model="scripted",
        host="http://127.0.0.1:11434",
        repetitions=repetitions,
    )
    assert RunSpec.model_validate_json(spec.model_dump_json()) == spec


@given(bad_rep=st.integers(max_value=0))
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_run_spec_and_cell_request_reject_non_positive_repetitions(
    sample_cell_request: CellRequest, bad_rep: int
) -> None:
    with pytest.raises(ValidationError):
        RunSpec(
            arms=("A",),
            task_ids=("analysis-de9im-001",),
            driver="scripted",
            model="scripted",
            host="http://127.0.0.1:11434",
            repetitions=bad_rep,
        )
    with pytest.raises(ValidationError):
        CellRequest(**{**sample_cell_request.model_dump(), "repetition": bad_rep})


def test_run_spec_forbids_extra_fields(sample_cell_request: CellRequest) -> None:
    assert sample_cell_request.repetition == 1
    with pytest.raises(ValidationError):
        RunSpec(
            arms=("A",),
            task_ids=("analysis-de9im-001",),
            driver="scripted",
            model="scripted",
            host="http://127.0.0.1:11434",
            bogus=True,  # type: ignore[call-arg]
        )
