"""PyQGIS sandbox gate: availability check + scrubbed-subprocess runner."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from experiment.services import qgis as qgis_service

app = typer.Typer(help="PyQGIS sandbox: check availability, run scripts scrubbed.")
console = Console(highlight=False)
SCRIPT_ARG = typer.Argument(..., help="PyQGIS script to run in the scrubbed sandbox")
ARTIFACTS_DIR_OPTION = typer.Option(Path("."), "--artifacts-dir", help="cwd for the script")
TIMEOUT_OPTION = typer.Option(120, "--timeout", help="wall-clock timeout in seconds")


def _remediation() -> str:
    lines = [
        "PyQGIS is not importable from this interpreter.",
        "The sandbox is the pixi `sandbox` feature (linux-64):",
        "it ships qgis 4.2, ollama, qgis-sdk from conda-forge.",
        "",
        '  pixi run -e sandbox python -c "import qgis.core; print(qgis.core.QGIS_VERSION)"',
        "",
        "or:  pixi shell -e sandbox   then re-run `qgis check`.",
        "In CI: ./.github/actions/setup with input environment: sandbox.",
    ]
    return "\n".join(lines)


def _print_unavailable() -> None:
    console.print(
        Panel(
            Text(_remediation(), style="yellow"),
            title="PyQGIS unavailable",
            border_style="yellow",
        )
    )


@app.command()
def check() -> None:
    """Report PyQGIS availability and versions; exit 3 when unavailable."""
    versions = qgis_service.qgis_versions()
    if versions is None:
        _print_unavailable()
        raise typer.Exit(code=3)
    lines = Text()
    for key, value in versions.items():
        lines.append(f"{key:>8}  ", style="bold")
        lines.append(value + "\n")
    console.print(Panel(lines, title="PyQGIS sandbox — available", border_style="green"))


@app.command()
def run(
    script: Path = SCRIPT_ARG,
    artifacts_dir: Path = ARTIFACTS_DIR_OPTION,
    timeout_s: int = TIMEOUT_OPTION,
) -> None:
    """Run SCRIPT with python -I and a minimal env (QT_QPA_PLATFORM=offscreen, no secrets)."""
    try:
        qgis_service.prepare_script(script, artifacts_dir)
    except qgis_service.ScriptNotFoundError:
        console.print(Text(f"missing script: {script}", style="red"))
        raise typer.Exit(code=2) from None
    except qgis_service.QgisUnavailableError:
        _print_unavailable()
        raise typer.Exit(code=3) from None
    console.print(_running_panel(script, artifacts_dir, timeout_s))
    try:
        completed = qgis_service.run_script(script, artifacts_dir, timeout_s)
    except qgis_service.SandboxTimeoutError:
        console.print(Text(f"script timed out after {timeout_s}s", style="red"))
        raise typer.Exit(code=4) from None
    _print_completed(completed)
    if completed.returncode != 0:
        raise typer.Exit(code=completed.returncode)


def _running_panel(script: Path, artifacts_dir: Path, timeout_s: int) -> Panel:
    return Panel(
        Text(f"{script}\ncwd={artifacts_dir}\ntimeout={timeout_s}s", style="bold"),
        title="PyQGIS sandbox — running",
        border_style="blue",
    )


def _print_completed(completed: qgis_service.SandboxRunResult) -> None:
    console.print(
        Panel(Text(completed.stdout[-8000:] or "(no stdout)"), title="stdout", border_style="green")
    )
    if completed.stderr.strip():
        console.print(
            Panel(Text(completed.stderr[-4000:], style="red"), title="stderr", border_style="red")
        )
