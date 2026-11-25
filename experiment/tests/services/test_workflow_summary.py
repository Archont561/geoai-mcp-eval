"""Unit tests for ``experiment.services.workflow_summary``."""

from __future__ import annotations

import json
from pathlib import Path

from experiment.services import workflow_summary


def test_render_summary_markdown_from_harvest_dir(tmp_path: Path) -> None:
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    (harvest / "env-pins.txt").write_text("repo_sha=deadbeef\npython=3.13\n", encoding="utf-8")
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
    md = workflow_summary.render_summary(harvest, "rid-sum")
    assert "rid-sum" in md
    assert "deadbeef" in md
    assert "COMPLETE" in md
