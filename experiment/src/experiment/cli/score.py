"""Oracle scoring, three-pass determinism gate, and score inspection commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.text import Text

from experiment.cli._render import print_score_table
from experiment.services import scoring
from experiment.services import tasks as tasks_service

app = typer.Typer(help="Score runs against the oracle, verify determinism, and view results.")
console = Console(highlight=False)

DEFAULT_TASK_ROOT = tasks_service.default_task_root()
ROOT_OPTION = typer.Option(DEFAULT_TASK_ROOT, "--root", help="Task suite root directory")
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable JSON")
TARGET_ARG = typer.Argument(..., help="Run directory or RunArchive .zip file")
TASK_ID_ARG = typer.Argument(..., help="Task identifier")
ARTIFACTS_OPTION = typer.Option(..., "--artifacts-dir", help="Trial directory to evaluate")


@app.command("eval")
def evaluate(
    target: Path = TARGET_ARG, root: Path = ROOT_OPTION, as_json: bool = JSON_OPTION
) -> None:
    """Re-score every trial in TARGET (run directory or zip archive) against the oracle."""
    summary = scoring.rescore_run(target, task_root=root)
    if summary is None:
        console.print(Text(f"no trials under {target}", style="red"))
        raise typer.Exit(code=1)
    if as_json:
        typer.echo(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
        return
    print_score_table(console, summary)


@app.command()
def determinism(
    task_id: str = TASK_ID_ARG,
    artifacts_dir: Path = ARTIFACTS_OPTION,
    root: Path = ROOT_OPTION,
) -> None:
    """Run the task oracle three times against fixed artifacts and emit JSON."""
    try:
        task_path, _ = tasks_service.get_task(task_id, root)
    except tasks_service.TaskNotFoundError as exc:
        raise typer.BadParameter(f"unknown task ID: {task_id}") from exc
    report = scoring.run_determinism_gate(task_path, artifacts_dir)
    typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if not report.passed:
        raise typer.Exit(code=1)


@app.command()
def show(target: Path = TARGET_ARG, as_json: bool = JSON_OPTION) -> None:
    """Display stored oracle scores from a run directory or RunArchive zip."""
    try:
        summary = scoring.load_summary(target)
    except scoring.SummaryNotFoundError as exc:
        console.print(Text(f"missing {exc}", style="red"))
        raise typer.Exit(code=1) from None
    if as_json:
        typer.echo(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
        return
    print_score_table(console, summary)
