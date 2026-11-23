"""Prototype commands: GIS MCP ops, agent runs, oracle scoring. Rich output."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from experiment import backends, gis_ops, mcp_client, prototype
from experiment.harness import (
    ARM_PREFIX,
    DRIVERS,
    TASK_ROOT,
    RunSpec,
    model_label,
    resolve_output_dir,
)

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
RUN_DIR_ARG = typer.Argument(..., help="prototype output dir containing <task>/arm-<A|B> cells")
SHOW_DIR_ARG = typer.Argument(..., help="prototype output dir containing summary.json")


def _parse_arms(raw: str) -> tuple[str, ...]:
    mapping = {"both": ("A", "B"), "a": ("A",), "b": ("B",)}
    key = raw.strip().lower()
    if key not in mapping:
        raise typer.BadParameter(f"--arm must be one of both|A|B, got {raw!r}")
    return mapping[key]


def _parse_tasks(raw: str) -> tuple[str, ...] | None:
    if raw.strip().lower() == "all":
        return None
    return tuple(part.strip() for part in raw.split(",") if part.strip())


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


async def _selftest_rows() -> list[tuple[str, str, str]]:
    tools = await mcp_client.list_tools()
    fixture = TASK_ROOT / "fixtures" / "analysis" / "poland-czechia.geojson"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    pol = await mcp_client.call_tool(
        "filter_features", {"geojson": payload, "property": "ISO_A3", "equals": "POL"}
    )
    cze = await mcp_client.call_tool(
        "filter_features", {"geojson": payload, "property": "ISO_A3", "equals": "CZE"}
    )
    de9im = await mcp_client.call_tool("relate_de9im", {"geojson_a": pol, "geojson_b": cze})
    admin = str(pol["features"][0]["properties"].get("ADMIN"))
    return [
        ("list_tools", f"{len(tools)} tools", ", ".join(tools[:5]) + " …"),
        ("filter_features POL", f"{len(pol['features'])} feature", admin),
        ("relate_de9im POL×CZE", de9im["relation"], de9im["de9im"]),
    ]


@app.command(name="mcp-selftest")
def mcp_selftest() -> None:
    """Spawn the MCP server over stdio, list tools, run 3 sample calls."""
    import asyncio

    with console.status("[bold]spinning up GIS MCP server over stdio…", spinner="dots"):
        rows = asyncio.run(_selftest_rows())
    table = Table(title="MCP self-test", header_style="bold cyan")
    table.add_column("check")
    table.add_column("result")
    table.add_column("detail", style="dim")
    for name, result, detail in rows:
        table.add_row(name, result, detail)
    console.print(table)


def _parse_run_spec(
    driver: str, model: str | None, host: str | None, arm: str, task: str, backend: str
) -> RunSpec:
    if driver not in DRIVERS:
        raise typer.BadParameter(f"--driver must be one of {', '.join(DRIVERS)}")
    try:
        profile = backends.resolve_profile(backend, host=host, model=model)
        if driver == "ollama":
            backends.require_api_key(profile)
    except backends.BackendError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return RunSpec(
        driver=driver,
        model=profile.model,
        host=str(profile.base_url),
        arms=_parse_arms(arm),
        task_ids=_parse_tasks(task),
        profile=profile,
    )


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
) -> None:
    """Run the 3 pilot tasks in arms A and/or B, then score with the oracle."""
    spec = _parse_run_spec(driver, model, host, arm, task, backend)
    out = resolve_output_dir(output_dir)
    console.print(_run_banner(spec, out))
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        overall = progress.add_task("cells …", total=None)
        summary = prototype.run_experiment(root, spec, out)
        progress.update(overall, description="cells done")
    _print_score_table(summary)
    console.print(_artifacts_panel(out))
    if any(cell["status"] == "error" for cell in summary["cells"]):
        raise typer.Exit(code=1)


def _artifacts_panel(out: Path) -> Panel:
    return Panel(
        Text.assemble(
            ("Artifacts: ", "bold"),
            (str(out), "magenta"),
            ("\nPer cell: transcript.jsonl · result.json|geojson · score.json\n", "dim"),
            ("Merged: summary.json", "dim"),
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


def _task_paths_by_id() -> dict[str, Path]:
    return {prototype.load_task(p)["id"]: p for p in prototype.discover_tasks(TASK_ROOT)}


def _rescore_cell(task_path: Path, cell: Path) -> dict:
    task_id = cell.parent.name
    arm = cell.name.removeprefix(ARM_PREFIX)
    report = prototype.score_cell(task_path, cell)
    return {
        **report,
        "task": task_id,
        "arm": arm,
        "status": "rescored",
        "wall_s": "—",
        "oracle_passed": report["passed"],
    }


def _rescore_cells(run_dir: Path, task_by_id: dict[str, Path]) -> list[dict]:
    cells = []
    for cell in sorted(run_dir.glob(f"*/{ARM_PREFIX}*")):
        task_id = cell.parent.name
        if cell.is_dir() and task_id in task_by_id:
            cells.append(_rescore_cell(task_by_id[task_id], cell))
    return cells


@app.command()
def score(run_dir: Path = RUN_DIR_ARG) -> None:
    """Re-score every cell in RUN_DIR with the committed oracle."""
    task_by_id = _task_paths_by_id()
    cells = _rescore_cells(run_dir, task_by_id)
    if not cells:
        console.print(Text(f"no cells under {run_dir}", style="red"))
        raise typer.Exit(code=1)
    summary = {
        "run_id": run_dir.name,
        "prototype": True,
        "driver": "rescore",
        "model": "—",
        "generated_at": "",
        "cells": cells,
        "passed": sum(1 for c in cells if c["oracle_passed"]),
        "total": len(cells),
    }
    _print_score_table(summary)


@app.command()
def show(run_dir: Path = SHOW_DIR_ARG) -> None:
    """Pretty-print a stored summary.json."""
    path = run_dir / "summary.json"
    if not path.is_file():
        console.print(Text(f"missing {path}", style="red"))
        raise typer.Exit(code=1)
    _print_score_table(json.loads(path.read_text(encoding="utf-8")))
