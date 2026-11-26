"""Unit tests for ``experiment.services.workflow_summary``."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.services import workflow_summary


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(run_id="rid-sum", sha="deadbeef")
@given(
    run_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20),
    sha=st.text(alphabet="0123456789abcdef", min_size=8, max_size=40),
)
def test_render_summary_markdown_from_harvest_dir(tmp_path: Path, run_id: str, sha: str) -> None:
    harvest = tmp_path / "harvest"
    harvest.mkdir(exist_ok=True)
    (harvest / "env-pins.txt").write_text(f"repo_sha={sha}\npython=3.13\n", encoding="utf-8")
    (harvest / "summary.json").write_text(
        json.dumps(
            {
                "complete": True,
                "expected_cells": ["analysis-de9im-001/A/rep-1"],
                "logged_cells": ["analysis-de9im-001/A/rep-1"],
                "missing": [],
                "oracle": {"analysis-de9im-001/A/rep-1": "pass"},
            }
        ),
        encoding="utf-8",
    )
    md = workflow_summary.render_summary(harvest, run_id)
    assert run_id in md
    assert sha in md
    assert "COMPLETE" in md
