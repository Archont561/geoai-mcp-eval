"""Pilot task validation and oracle determinism commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from experiment.oracle import run_determinism_gate
from experiment.task_suite import validate_suite

app = typer.Typer(help="Prepare and verify the pilot task suite.")
DEFAULT_TASK_ROOT = Path("experiment/tasks")
ROOT_OPTION = typer.Option(DEFAULT_TASK_ROOT, "--root")
TASK_ID_ARGUMENT = typer.Argument(...)
ARTIFACTS_OPTION = typer.Option(..., "--artifacts-dir")


def _find_task(root: Path, task_id: str) -> Path:
    for path in sorted(root.glob("*.yaml")):
        try:
            task = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(task, dict) and task.get("id") == task_id:
            return path
    raise typer.BadParameter(f"unknown task ID: {task_id}")


@app.command()
def validate(root: Path = ROOT_OPTION) -> None:
    """Validate task schemas, fixtures, oracle types, and required trap coverage."""
    report = validate_suite(root)
    if report.passed:
        typer.echo(
            f"Task suite valid: {report.task_count} tasks; pilot traps covered: "
            f"{', '.join(sorted(report.traps_found))}"
        )
        return
    for issue in report.issues:
        typer.echo(f"ERROR: {issue}")
    raise typer.Exit(code=1)


@app.command()
def determinism(
    task_id: str = TASK_ID_ARGUMENT,
    artifacts_dir: Path = ARTIFACTS_OPTION,
    root: Path = ROOT_OPTION,
) -> None:
    """Run the task oracle three times against fixed artifacts and report consistency."""
    task_path = _find_task(root, task_id)
    report = run_determinism_gate(task_path, artifacts_dir)
    typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if not report.passed:
        raise typer.Exit(code=1)
