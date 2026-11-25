"""Paradigm-specific experiment execution commands (mcp, codegen, all, cell, smoke)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

from experiment.cli._render import print_score_table
from experiment.domain.run import Arm
from experiment.services import archive as archive_service
from experiment.services import runs
from experiment.services import tasks as tasks_service
from experiment.services import workflow as workflow_service
from experiment.services.runs import TASK_ROOT, RunSpec, model_label, resolve_output_dir

app = typer.Typer(help="Execute experiment trials per paradigm or run a quick smoke probe.")
console = Console(highlight=False)

ROOT_OPTION = typer.Option(TASK_ROOT, "--root", help="Task suite root directory")
DRIVER_OPTION = typer.Option(
    "scripted", "--driver", help="scripted (deterministic canned plan) | ollama (live LLM)"
)
MODEL_OPTION = typer.Option(
    None, "--model", envvar="EXPERIMENT_MODEL", help="Override the backend profile model tag"
)
HOST_OPTION = typer.Option(
    None, "--host", envvar="EXPERIMENT_HOST", help="Override the backend base URL"
)
BACKEND_OPTION = typer.Option(
    "local", "--backend", envvar="EXPERIMENT_BACKEND", help="Backend profile from backends.toml"
)
TASK_OPTION = typer.Option("all", "--task", help="all | comma-separated task IDs")
REPETITIONS_OPTION = typer.Option(
    1, "--repetitions", envvar="EXPERIMENT_REPETITIONS", help="Repetitions per (task, arm) cell"
)
OUTPUT_OPTION = typer.Option(None, "--output-dir", help="Output directory for run artifacts")
MAX_CELL_TOKENS_OPTION = typer.Option(
    None, "--max-cell-tokens", help="Abort cell if reported tokens exceed this positive integer"
)
CACHE_OPTION = typer.Option(
    True,
    "--cache/--no-cache",
    envvar="EXPERIMENT_USE_LLM_CACHE",
    help="Use or bypass the digest-keyed LLM completion cache",
)
CACHE_DIR_OPTION = typer.Option(None, "--cache-dir", help="Override LLM completion cache dir")
ENFORCE_OPTION = typer.Option(
    "semantic_repair",
    "--enforce",
    envvar="EXPERIMENT_ENFORCE",
    help="MCP enforcement level (none|declarative|syntactic|semantic_repair|transactional|N0..N4)",
)
PACK_ZIP_OPTION = typer.Option(
    False, "--pack-zip", help="Also pack completed run into a single RunArchive zip"
)

CELL_ARM_OPT = typer.Option("A", "--arm", envvar="EXPERIMENT_ARM", help="Experiment arm (A or B)")
CELL_TASK_OPT = typer.Option(..., "--task-id", envvar="EXPERIMENT_TASK_ID", help="Task identifier")
CELL_REP_OPT = typer.Option(1, "--repetition", envvar="EXPERIMENT_REPETITION", help="Repetition")
CELL_STAGE_OPT = typer.Option(
    "smoke", "--stage", envvar="EXPERIMENT_STAGE", help="Pipeline stage (smoke or pilot)"
)
CELL_ENFORCE_OPT = typer.Option(
    "N3", "--enforce", envvar="EXPERIMENT_ENFORCE", help="MCP enforcement depth (N1..N4)"
)
CELL_MODEL_OPT = typer.Option(
    "qwen2.5:3b", "--model", envvar=["EXPERIMENT_MODEL", "MODEL"], help="Ollama model tag"
)
CELL_RUN_ID_OPT = typer.Option(
    "", "--run-id", envvar=["EXPERIMENT_RUN_ID", "RUN_ID"], help="Run identifier"
)
CELL_CACHE_OPT = typer.Option(
    False,
    "--cache/--no-cache",
    "--use-cache/--no-cache",
    envvar="EXPERIMENT_USE_LLM_CACHE",
    help="Use local SQLite LLM completion cache",
)


class _RunOptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arms: str
    task: str
    root: Path
    output_dir: Path | None
    enforce: str = "none"
    repetitions: int = 1
    driver: str
    backend: str
    model: str | None
    host: str | None
    max_cell_tokens: int | None
    use_cache: bool
    cache_dir: Path | None
    pack_zip: bool


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
        title="experiment · run",
        border_style="blue",
    )


def _run_with_progress(root: Path, spec: RunSpec, out: Path) -> runs.RunSummary:
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


def _execute_run(opts: _RunOptions) -> None:
    try:
        spec = runs.parse_run_spec(
            runs.RunSpecInput(
                driver=opts.driver,
                model=opts.model,
                host=opts.host,
                arm=opts.arms,
                task=opts.task,
                backend=opts.backend,
                max_cell_tokens=opts.max_cell_tokens,
                use_cache=opts.use_cache,
                cache_dir=opts.cache_dir,
                enforce=opts.enforce,
                repetitions=opts.repetitions,
            )
        )
    except runs.RunSpecError as exc:
        raise typer.BadParameter(str(exc)) from exc
    out = resolve_output_dir(opts.output_dir)
    console.print(_run_banner(spec, out))
    summary = _run_with_progress(opts.root, spec, out)
    print_score_table(console, summary)
    if opts.pack_zip:
        _, zip_path = archive_service.pack_archive(archive_service.PackOptions(source_dir=out))
        console.print(Text(f"Archive written: {zip_path}", style="green"))
    if any(cell.status != "ok" for cell in summary.cells):
        raise typer.Exit(code=1)


_RUN_FIELDS = (
    "arms",
    "task",
    "root",
    "output_dir",
    "enforce",
    "repetitions",
    "driver",
    "backend",
    "model",
    "host",
    "max_cell_tokens",
    "use_cache",
    "cache_dir",
    "pack_zip",
)


def _register_enforced_cmd(name: str, arms: str, help_text: str) -> None:
    @app.command(name, help=help_text)
    def _cmd(  # noqa: CC102
        driver: str = DRIVER_OPTION,
        model: str | None = MODEL_OPTION,
        host: str | None = HOST_OPTION,
        task: str = TASK_OPTION,
        repetitions: int = REPETITIONS_OPTION,
        enforce: str = ENFORCE_OPTION,
        output_dir: Path | None = OUTPUT_OPTION,
        root: Path = ROOT_OPTION,
        backend: str = BACKEND_OPTION,
        max_cell_tokens: int | None = MAX_CELL_TOKENS_OPTION,
        use_cache: bool = CACHE_OPTION,
        cache_dir: Path | None = CACHE_DIR_OPTION,
        pack_zip: bool = PACK_ZIP_OPTION,
    ) -> None:
        t1 = (arms, task, root, output_dir, enforce, repetitions)
        t2 = (driver, backend, model, host)
        t3 = (max_cell_tokens, use_cache, cache_dir, pack_zip)
        _execute_run(_RunOptions.model_validate(dict(zip(_RUN_FIELDS, t1 + t2 + t3, strict=True))))


_register_enforced_cmd("mcp", "A", "Run Arm A (typed MCP paradigm) trials.")
_register_enforced_cmd("all", "both", "Run all agent paradigms (typed MCP + codegen).")


@app.command("codegen")
def run_codegen(  # noqa: CC102
    driver: str = DRIVER_OPTION,
    model: str | None = MODEL_OPTION,
    host: str | None = HOST_OPTION,
    task: str = TASK_OPTION,
    repetitions: int = REPETITIONS_OPTION,
    output_dir: Path | None = OUTPUT_OPTION,
    root: Path = ROOT_OPTION,
    backend: str = BACKEND_OPTION,
    max_cell_tokens: int | None = MAX_CELL_TOKENS_OPTION,
    use_cache: bool = CACHE_OPTION,
    cache_dir: Path | None = CACHE_DIR_OPTION,
    pack_zip: bool = PACK_ZIP_OPTION,
) -> None:
    """Run Arm B (free Python/PyQGIS codegen paradigm) trials (enforcement fixed to none)."""
    t1 = ("B", task, root, output_dir, "none", repetitions)
    t2 = (driver, backend, model, host)
    t3 = (max_cell_tokens, use_cache, cache_dir, pack_zip)
    _execute_run(_RunOptions.model_validate(dict(zip(_RUN_FIELDS, t1 + t2 + t3, strict=True))))


@app.command("cell")
def run_cell(  # noqa: CC102
    arm: Arm = CELL_ARM_OPT,
    task_id: str = CELL_TASK_OPT,
    repetition: int = CELL_REP_OPT,
    stage: Literal["smoke", "pilot"] = CELL_STAGE_OPT,
    enforce: Literal["N1", "N2", "N3", "N4"] = CELL_ENFORCE_OPT,
    model: str = CELL_MODEL_OPT,
    run_id: str = CELL_RUN_ID_OPT,
    use_cache: bool = CELL_CACHE_OPT,
) -> None:
    """Run one CI matrix cell (arm, task, repetition) for smoke or pilot stage."""
    spec = workflow_service.WorkflowCellSpec(
        arm=arm,
        task_id=task_id,
        repetition=repetition,
        stage=stage,
        enforce=enforce,
        model=model,
        run_id=run_id,
        use_cache=use_cache,
    )
    try:
        cell_dir = workflow_service.run_workflow_cell(spec)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"cell complete: arm={arm} task={task_id} rep={repetition} -> {cell_dir}")


@app.command("smoke")
def run_smoke(root: Path = ROOT_OPTION) -> None:
    """Fast non-agent plumbing probe verifying CLI and task suite wiring."""
    discovered = tasks_service.list_tasks(root)
    typer.echo(f"smoke ok: {len(discovered)} tasks ready")
