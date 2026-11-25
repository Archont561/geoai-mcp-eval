"""Benchmark task commands: list, inspect, and validate the task suite."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from experiment.services import tasks as tasks_service

app = typer.Typer(help="List, inspect, and validate benchmark tasks.")
console = Console(no_color=True, highlight=False, markup=False)
rich_console = Console(highlight=False, width=120)

DEFAULT_TASK_ROOT = tasks_service.default_task_root()
ROOT_OPTION = typer.Option(DEFAULT_TASK_ROOT, "--root", help="Task suite root directory")
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable JSON")
TASK_ID_ARG = typer.Argument(..., help="Task identifier (e.g. analysis-de9im-001)")


def _task_json_rows(suite_tasks: list) -> list[dict]:
    return [
        {
            "id": task.id,
            "family": task.family,
            "tier": task.difficulty_rubric.tier,
            "expressible": task.difficulty_rubric.expressible,
            "contamination": task.provenance.contamination,
            "assertions": len(task.oracle.assertions),
            "required_traps": list(task.required_traps),
        }
        for task in suite_tasks
    ]


@app.command("ls")
def list_tasks(root: Path = ROOT_OPTION, as_json: bool = JSON_OPTION) -> None:
    """List all tasks in the suite with family, tier, expressibility, and traps."""
    suite_tasks = tasks_service.list_tasks(root)
    if as_json:
        typer.echo(json.dumps(_task_json_rows(suite_tasks), indent=2))
        return
    table = Table(title=f"Benchmark tasks ({len(suite_tasks)})", header_style="bold cyan")
    table.add_column("id", no_wrap=True)
    for col in ("family", "tier", "expressible", "contamination", "assertions", "traps"):
        table.add_column(col)
    for task in suite_tasks:
        table.add_row(
            task.id,
            task.family,
            str(task.difficulty_rubric.tier),
            task.difficulty_rubric.expressible,
            task.provenance.contamination,
            str(len(task.oracle.assertions)),
            ", ".join(task.required_traps) or "—",
        )
    rich_console.print(table)


def _task_detail_payload(path: Path, task: object) -> dict[str, object]:
    return {
        "file": path.name,
        "id": task.id,
        "title": task.title,
        "family": task.family,
        "tier": task.difficulty_rubric.tier,
        "expressible": task.difficulty_rubric.expressible,
        "contamination": task.provenance.contamination,
        "fixture_input": task.fixture_input,
        "required_traps": list(task.required_traps),
        "human_baseline_status": task.human_baseline.status,
        "prompt": task.prompt,
        "assertions": [dict(a) for a in task.oracle.assertions],
    }


@app.command()
def show(task_id: str = TASK_ID_ARG, root: Path = ROOT_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Display detailed metadata, prompt, fixtures, and assertions for one task."""
    try:
        path, task = tasks_service.get_task(task_id, root)
    except tasks_service.TaskNotFoundError as exc:
        raise typer.BadParameter(f"unknown task ID: {task_id}") from exc
    if as_json:
        typer.echo(json.dumps(_task_detail_payload(path, task), indent=2, sort_keys=True))
        return
    assertion_lines = "\n".join(
        f"  - {a.get('id', '?')} ({a.get('type', '?')})" for a in task.oracle.assertions
    )
    body = Text(
        f"File: {path.name}\n"
        f"Title: {task.title}\n"
        f"Family: {task.family} | Tier: {task.difficulty_rubric.tier} | "
        f"Expressible: {task.difficulty_rubric.expressible}\n"
        f"Contamination: {task.provenance.contamination} | "
        f"Fixture: {task.fixture_input}\n"
        f"Traps: {', '.join(task.required_traps) or 'none'}\n"
        f"Human baseline: {task.human_baseline.status}\n\n"
        f"Prompt:\n{task.prompt}\n\n"
        f"Oracle assertions ({len(task.oracle.assertions)}):\n{assertion_lines}"
    )
    rich_console.print(Panel(body, title=task.id, border_style="cyan"))


@app.command()
def validate(root: Path = ROOT_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Validate task schemas, fixtures, oracle types, and required trap coverage."""
    report = tasks_service.validate_suite(root)
    if as_json:
        payload = {
            "passed": report.passed,
            "task_count": report.task_count,
            "traps_found": sorted(report.traps_found),
            "issues": [str(issue) for issue in report.issues],
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        if not report.passed:
            raise typer.Exit(code=1)
        return
    if report.passed:
        console.print(
            Text(
                f"Task suite valid: {report.task_count} tasks; pilot traps covered: "
                f"{', '.join(sorted(report.traps_found))}"
            )
        )
        return
    for issue in report.issues:
        console.print(Text(f"ERROR: {issue}"))
    raise typer.Exit(code=1)
