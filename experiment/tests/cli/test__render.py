"""Unit tests for ``experiment.cli._render``."""

from __future__ import annotations

from rich.console import Console

from experiment.cli._render import print_score_table
from experiment.services.reports import CellSummary, CheckView, RunSummary


def test_print_score_table_renders_summary() -> None:
    console = Console(record=True)
    summary = RunSummary(
        run_id="r1",
        prototype=True,
        driver="scripted",
        model="scripted",
        generated_at="2026-11-25T00:00:00Z",
        cells=(
            CellSummary(
                task="analysis-de9im-001",
                arm="A",
                status="ok",
                oracle_passed=True,
                checks=(CheckView(assertion_id="c1", passed=True, detail="ok"),),
                wall_s=0.5,
            ),
        ),
        passed=1,
        total=1,
    )
    print_score_table(console, summary)
    rendered = console.export_text()
    assert "analysis-de9im-001" in rendered
    assert "1/1 cells oracle-passed" in rendered
