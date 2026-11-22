"""Hello command — dropped into cli/ and auto-discovered as a sub-command."""

from __future__ import annotations

import typer

app = typer.Typer(help="Say hello.")


@app.command()
def hello(name: str = "world") -> None:
    """Print a greeting for NAME."""
    typer.echo(f"Hello, {name}!")
