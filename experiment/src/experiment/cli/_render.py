"""Shared Rich rendering helpers for CLI commands (not a mounted command group)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from experiment.services.reports import RunSummary


def print_score_table(console: Console, summary: RunSummary) -> None:
    """Render an oracle score table and pass-rate summary line."""
    table = Table(title="Oracle scores", header_style="bold cyan")
    for col in ("task", "arm", "status", "oracle", "checks"):
        table.add_column(col)
    table.add_column("wall_s", justify="right")
    for cell in summary.trials:
        verdict = "✓" if cell.oracle_passed else "✗"
        status_style = "green" if cell.status == "ok" else "red"
        oracle_style = "green" if cell.oracle_passed else "red"
        checks = " · ".join(f"{'✓' if c.passed else '✗'} {c.assertion_id}" for c in cell.checks)
        table.add_row(
            cell.task,
            cell.arm,
            Text(cell.status, style=status_style),
            Text(verdict, style=oracle_style),
            checks,
            str(cell.wall_s),
        )
    console.print(table)
    style = "green" if summary.passed == summary.total else "yellow"
    msg = f"{summary.passed}/{summary.total} trials oracle-passed"
    console.print(Text(msg, style=f"bold {style}"))
