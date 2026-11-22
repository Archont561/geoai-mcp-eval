"""PyQGIS sandbox gate: availability check + scrubbed-subprocess runner."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from experiment.harness import scrubbed_env

app = typer.Typer(help="PyQGIS sandbox: check availability, run scripts scrubbed.")
console = Console(highlight=False)
SCRIPT_ARG = typer.Argument(..., help="PyQGIS script to run in the scrubbed sandbox")
ARTIFACTS_DIR_OPTION = typer.Option(Path("."), "--artifacts-dir", help="cwd for the script")
TIMEOUT_OPTION = typer.Option(120, "--timeout", help="wall-clock timeout in seconds")


def _qgis_versions() -> dict[str, str] | None:
    try:
        import qgis.core  # type: ignore[import-not-found]
    except ImportError:
        return None
    versions: dict[str, str] = {}
    try:
        versions["qgis"] = qgis.core.Qgis.QGIS_VERSION
    except AttributeError:
        versions["qgis"] = getattr(qgis.core, "QGIS_VERSION", "unknown")
    for key, attr in (("gdal", "GDAL_VERSION"), ("geos", "GEOS_VERSION"), ("proj", "PROJ_VERSION")):
        value = getattr(qgis.core, attr, None) or os.environ.get(f"{key.upper()}_VERSION")
        versions[key] = str(value) if value else "unknown"
    versions["python"] = sys.version.split()[0]
    return versions


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
    versions = _qgis_versions()
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
    if not script.is_file():
        console.print(Text(f"missing script: {script}", style="red"))
        raise typer.Exit(code=2)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if _qgis_versions() is None:
        _print_unavailable()
        raise typer.Exit(code=3)
    console.print(_running_panel(script, artifacts_dir, timeout_s))
    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(script.resolve())],
            cwd=artifacts_dir,
            env=scrubbed_env(artifacts_dir, qt_platform="offscreen"),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
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


def _print_completed(completed: subprocess.CompletedProcess[str]) -> None:
    console.print(
        Panel(Text(completed.stdout[-8000:] or "(no stdout)"), title="stdout", border_style="green")
    )
    if completed.stderr.strip():
        console.print(
            Panel(Text(completed.stderr[-4000:], style="red"), title="stderr", border_style="red")
        )
