"""Properties of the pilot cell specification."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.workflow_pilot import WorkflowCellSpec


@given(
    repetition=st.integers(min_value=1, max_value=100), stage=st.sampled_from(["pilot", "smoke"])
)
def test_workflow_cell_spec_roundtrips(repetition: int, stage: str) -> None:
    spec = WorkflowCellSpec.model_validate(
        {"arm": "A", "task_id": "analysis-de9im-001", "repetition": repetition, "stage": stage}
    )
    assert WorkflowCellSpec.model_validate_json(spec.model_dump_json()) == spec


@given(repetition=st.integers(max_value=0))
def test_workflow_cell_spec_rejects_nonpositive_repetitions(repetition: int) -> None:
    with pytest.raises(ValidationError):
        WorkflowCellSpec(arm="A", task_id="t1", repetition=repetition)
