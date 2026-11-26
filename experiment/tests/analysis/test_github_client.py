"""Unit and property tests for ``experiment.analysis.github_client`` (``PyGithub`` + ``httpx``)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.analysis import (
    WorkflowRunSummary,
)


@given(
    database_id=st.integers(min_value=1, max_value=10**12),
    head_sha=st.text(alphabet="0123456789abcdef", min_size=7, max_size=40),
    title=st.text(min_size=1, max_size=40),
)
def test_workflow_run_summary_roundtrips_for_arbitrary_runs(
    database_id: int, head_sha: str, title: str
) -> None:
    summary = WorkflowRunSummary(
        database_id=database_id,
        head_sha=head_sha,
        status="completed",
        conclusion="success",
        created_at="2026-11-24T12:00:00Z",
        display_title=title,
        url=f"https://example.invalid/{database_id}",
    )
    assert WorkflowRunSummary.model_validate_json(summary.model_dump_json()) == summary
    with pytest.raises(ValidationError):
        WorkflowRunSummary.model_validate({**summary.model_dump(), "extra": 1})
