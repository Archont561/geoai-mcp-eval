"""Unit tests for ``experiment.cli._render``."""

from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st
from rich.console import Console

from experiment.cli._render import print_score_table
from experiment.services.reports import CellSummary, CheckView, RunSummary


@example(task_id="analysis-de9im-001")
@given(task_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20))
def test_print_score_table_renders_summary(task_id: str) -> None:
    console = Console(record=True)
    summary = RunSummary(
        run_id="r1",
        prototype=True,
        driver="scripted",
        model="scripted",
        generated_at="2026-11-25T00:00:00Z",
        cells=(
            CellSummary(
                task=task_id,
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
    assert task_id in rendered
    assert "1/1 trials oracle-passed" in rendered
