"""Prototype commands: GIS MCP ops, agent runs, oracle scoring. Rich output."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from experiment import gis_ops
from experiment.harness import TASK_ROOT, RunSpec, model_label, resolve_output_dir
from experiment.services import mcp_selftest as mcp_selftest_service
from experiment.services import runs, scoring

app = typer.Typer(
    help="Prototype agent runs + scoring (pipeline verification, not a study result)."
)
console = Console(highlight=False)
ROOT_OPTION = typer.Option(TASK_ROOT, "--root")
DRIVER_OPTION = typer.Option(
    "scripted", "--driver", help="scripted (deterministic canned plan) | ollama (real model)"
)
MODEL_OPTION = typer.Option(
    None, "--model", help="override the profile's model (prototype only; not the study pin)"
)
HOST_OPTION = typer.Option(
    None,
    "--host",
    help="override the profile's base_url (local default: $OLLAMA_HOST or http://127.0.0.1:11434)",
)
BACKEND_OPTION = typer.Option(
    "local",
    "--backend",
    help="profile from experiment/backends.toml (local, remote-ollama, free-open, …)",
)
ARMS_OPTION = typer.Option("both", "--arm", help="both | A | B")
TASK_OPTION = typer.Option("all", "--task", help="all | comma-separated task ids")
OUTPUT_OPTION = typer.Option(None, "--output-dir", help="defaults to results/prototype-<utc stamp>")
MAX_CELL_TOKENS_OPTION = typer.Option(
    None,
    "--max-cell-tokens",
    help="abort a cell if reported total tokens exceed this positive integer cap",
)
NO_CACHE_OPTION = typer.Option(
    False,
    "--no-cache",
    help="bypass the digest-keyed LLM completion cache and force fresh completions",
)
CACHE_DIR_OPTION = typer.Option(
    None,
    "--cache-dir",
    help="override the LLM completion cache directory (defaults to .cache/llm)",
)
RUN_DIR_ARG = typer.Argument(..., help="prototype output dir containing <task>/arm-<A|B> cells")
SHOW_DIR_ARG = typer.Argument(..., help="prototype output dir containing summary.json")


@app.command()
def ops() -> None:
    """List the GIS operations the MCP server exposes (Arm A tool catalogue)."""
    table = Table(title="GIS prototype operations (MCP tools)", header_style="bold cyan")
    table.add_column("tool", style="cyan", no_wrap=True)
    table.add_column("signature", style="dim")
    table.add_column("summary")
    for name, func in sorted(gis_ops.OPS.items()):
        doc = (func.__doc__ or "").strip().splitlines()[0]
        params = ", ".join(list(func.__annotations__)[:-1])
        table.add_row(name, f"({params})", doc)
    console.print(table)
    console.print(
        Text(
            f"{len(gis_ops.OPS)} ops — not the frozen catalogue; see decision 0004.",
            style="yellow",
        )
    )


@app.command(name="mcp-selftest")
def mcp_selftest() -> None:
    """Spawn the MCP server over stdio, list tools, run 3 sample calls."""
    import asyncio

    with console.status("[bold]spinning up GIS MCP server over stdio…", spinner="dots"):
        rows = asyncio.run(mcp_selftest_service.selftest_rows())
    table = Table(title="MCP self-test", header_style="bold cyan")
    table.add_column("check")
    table.add_column("result")
    table.add_column("detail", style="dim")
    for name, result, detail in rows:
        table.add_row(name, result, detail)
    console.print(table)


def _run_banner(spec: RunSpec, out: Path) -> Panel:
    return Panel(
        Text.assemble(
            ("driver=", "bold"),
            (spec.driver, "cyan"),
            ("  model=", "bold"),
            (model_label(spec.driver, spec.model), "cyan"),
            ("  arms=", "bold"),
            (",".join(spec.arms), "cyan"),
            ("\nOutput: ", "bold"),
            (str(out), "magenta"),
            ("\nPROTOTYPE — pipeline verification only, not a study result.", "yellow"),
        ),
        title="experiment · prototype run",
        border_style="blue",
    )


def _run_with_progress(root: Path, spec: RunSpec, out: Path) -> dict:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        overall = progress.add_task("cells …", total=None)
        summary = runs.run_experiment(root, spec, out)
        progress.update(overall, description="cells done")
    return summary


def _finish_run(root: Path, spec: RunSpec, output_dir: Path | None) -> None:
    out = resolve_output_dir(output_dir)
    console.print(_run_banner(spec, out))
    summary = _run_with_progress(root, spec, out)
    _print_score_table(summary)
    console.print(_artifacts_panel(out))
    if any(cell["status"] != "ok" for cell in summary["cells"]):
        raise typer.Exit(code=1)


@app.command()
def run(  # noqa: CC102
    driver: str = DRIVER_OPTION,
    model: str | None = MODEL_OPTION,
    host: str | None = HOST_OPTION,
    arm: str = ARMS_OPTION,
    task: str = TASK_OPTION,
    output_dir: Path | None = OUTPUT_OPTION,
    root: Path = ROOT_OPTION,
    backend: str = BACKEND_OPTION,
    max_cell_tokens: int | None = MAX_CELL_TOKENS_OPTION,
    no_cache: bool = NO_CACHE_OPTION,
    cache_dir: Path | None = CACHE_DIR_OPTION,
) -> None:
    """Run the 3 pilot tasks in arms A and/or B, then score with the oracle."""
    try:
        spec = runs.parse_run_spec(
            driver,
            model,
            host,
            arm,
            task,
            backend,
            max_cell_tokens=max_cell_tokens,
            use_cache=not no_cache,
            cache_dir=cache_dir,
        )
    except runs.RunSpecError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _finish_run(root, spec, output_dir)


def _artifacts_panel(out: Path) -> Panel:
    return Panel(
        Text.assemble(
            ("Artifacts: ", "bold"),
            (str(out), "magenta"),
            ("\nPer cell: transcript.jsonl · result.json|geojson · score.json\n", "dim"),
            ("Merged: summary.json · manifest.json", "dim"),
        ),
        title="where the outputs are",
        border_style="green",
    )


def _print_score_table(summary: dict) -> None:
    table = Table(title="Oracle scores", header_style="bold cyan")
    table.add_column("task")
    table.add_column("arm")
    table.add_column("status")
    table.add_column("oracle")
    table.add_column("checks")
    table.add_column("wall_s", justify="right")
    for cell in summary["cells"]:
        verdicts = "✓" if cell["oracle_passed"] else "✗"
        status_style = "green" if cell["status"] == "ok" else "red"
        oracle_style = "green" if cell["oracle_passed"] else "red"
        checks = " · ".join(
            f"{'✓' if c['passed'] else '✗'} {c['assertion_id']}" for c in cell["checks"]
        )
        table.add_row(
            cell["task"],
            cell["arm"],
            Text(cell["status"], style=status_style),
            Text(verdicts, style=oracle_style),
            checks,
            str(cell["wall_s"]),
        )
    console.print(table)
    passed, total = summary["passed"], summary["total"]
    style = "green" if passed == total else "yellow"
    console.print(Text(f"{passed}/{total} cells oracle-passed", style=f"bold {style}"))


@app.command()
def score(run_dir: Path = RUN_DIR_ARG) -> None:
    """Re-score every cell in RUN_DIR with the committed oracle."""
    summary = scoring.rescore_run(run_dir)
    if summary is None:
        console.print(Text(f"no cells under {run_dir}", style="red"))
        raise typer.Exit(code=1)
    _print_score_table(summary)


@app.command()
def show(run_dir: Path = SHOW_DIR_ARG) -> None:
    """Pretty-print a stored summary.json."""
    try:
        summary = scoring.load_summary(run_dir)
    except scoring.SummaryNotFoundError as exc:
        console.print(Text(f"missing {exc}", style="red"))
        raise typer.Exit(code=1) from None
    _print_score_table(summary)
