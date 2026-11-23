"""Analysis data preparation commands."""

from __future__ import annotations

from pathlib import Path

import typer

from experiment import analyze

app = typer.Typer(help="Prepare analysis-ready data from run results.")
TASKS_OPTION = typer.Option(Path("experiment/tasks"), "--tasks", help="task suite directory")


@app.command()
def flatten(results: Path, tasks: Path = TASKS_OPTION) -> None:
    """Print the flat binary predicate matrix for a results directory.

    score.json files stay verbose; this prints exactly run keys plus one
    0/1 column per named predicate. Nothing is written to disk.
    """
    frame = analyze.flatten(results, tasks)
    if frame.empty:
        typer.echo("no score.json files found")
        raise typer.Exit(code=1)
    typer.echo(frame.to_string(index=False))
