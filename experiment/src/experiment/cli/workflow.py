"""Experiment workflow subcommands (preflight, model, run, harvest, summary, backend-check).

Auto-discovered by ``experiment.cli._loader`` as ``experiment workflow ...`` and
exposed to Tasknest via manifest autodiscovery in ``experiment/pyproject.toml``.
Every option accepts both explicit CLI flags and environment variables so CI
steps and ``pixi run tools run experiment <task>`` stay flag-free one-liners.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

import typer

from experiment.services import backend_check as backend_check_service
from experiment.services import workflow as workflow_service
from experiment.services import workflow_summary

app = typer.Typer(help="Experiment CI/local pipeline workflow commands.")

RUN_ID_OPT = typer.Option("", "--run-id", envvar="RUN_ID", help="Run identifier")
MODEL_OPT = typer.Option("qwen2.5:3b", "--model", envvar="MODEL", help="Ollama model tag")
ARM_OPT = typer.Option("A", "--arm", envvar="EXPERIMENT_ARM", help="Experiment arm (A or B)")
TASK_ID_OPT = typer.Option(
    ..., "--task-id", envvar="EXPERIMENT_TASK_ID", help="Pilot/study task id"
)
REP_OPT = typer.Option(1, "--repetition", envvar="EXPERIMENT_REPETITION", help="Repetition number")
STAGE_OPT = typer.Option(
    "smoke", "--stage", envvar="EXPERIMENT_STAGE", help="Pipeline stage (smoke or pilot)"
)
ENFORCE_OPT = typer.Option(
    "N3", "--enforce", envvar="EXPERIMENT_ENFORCE", help="MCP enforcement depth (N1..N4)"
)
USE_CACHE_OPT = typer.Option(
    False,
    "--use-cache/--no-cache",
    envvar="EXPERIMENT_USE_LLM_CACHE",
    help="Use local SQLite LLM completion cache",
)
HARVEST_DIR_OPT = typer.Option(
    Path("harvest"),
    "--harvest-dir",
    envvar="EXPERIMENT_HARVEST_DIR",
    help="Directory containing downloaded or local cell outputs",
)
ARMS_OPT = typer.Option(
    "A,B",
    "--arms",
    envvar="EXPERIMENT_ARMS",
    help="Comma-separated arms expected in harvest (e.g. A,B)",
)
REPS_OPT = typer.Option(
    2,
    "--repetitions",
    envvar="EXPERIMENT_REPETITIONS",
    help="Expected repetitions per (arm, task)",
)
FAIL_MISSING_OPT = typer.Option(
    True,
    "--fail-on-missing/--no-fail-on-missing",
    envvar="EXPERIMENT_FAIL_ON_MISSING",
    help="Fail loudly when any expected cell is missing",
)
SKIP_ORACLE_OPT = typer.Option(
    False,
    "--skip-oracle/--no-skip-oracle",
    envvar="EXPERIMENT_SKIP_ORACLE",
    help="Skip the oracle determinism gate (smoke stage only)",
)
BACKEND_OPT = typer.Option(
    "remote-ollama",
    "--backend",
    envvar="EXPERIMENT_BACKEND",
    help="Backend profile from experiment/backends.toml",
)
SSH_HOST_OPT = typer.Option(
    None,
    "--ssh-host",
    envvar="OLLAMA_SSH_HOST",
    help="SSH host for ControlMaster tunnel verification",
)
CONTROL_PATH_OPT = typer.Option(
    None,
    "--control-path",
    envvar="OLLAMA_CONTROL_PATH",
    help="Path to SSH ControlMaster socket",
)
EXPECTED_DIGEST_OPT = typer.Option(
    None,
    "--expected-digest",
    envvar="EXPERIMENT_EXPECTED_DIGEST",
    help="Expected Ollama model digest pin",
)
OPT_MODEL_OPT = typer.Option(
    None, "--model", envvar="EXPERIMENT_MODEL", help="Optional model override"
)
HOST_OPT = typer.Option(None, "--host", envvar="OLLAMA_HOST", help="Optional base_url override")
POLL_TIMEOUT_OPT = typer.Option(
    30.0,
    "--poll-timeout-s",
    envvar="EXPERIMENT_POLL_TIMEOUT_S",
    help="Seconds to poll /v1/models for expected digest",
)


@app.command()
def preflight(run_id: str = RUN_ID_OPT) -> None:
    """Validate the pilot task suite and pin the run environment."""
    try:
        rid, pins, pins_path = workflow_service.run_preflight(run_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"run_id={rid}")
    for key, value in pins.items():
        typer.echo(f"{key}={value}")
    typer.echo(f"env-pins written to {pins_path}")
    typer.echo(f"RUN_ID={rid}")


@app.command()
def model(model: str = MODEL_OPT, run_id: str = RUN_ID_OPT) -> None:
    """Start Ollama, pull the pinned model, and record its digest."""
    try:
        digest, snippet, run_dir = workflow_service.run_model(model=model, run_id=run_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"model={model}")
    typer.echo(f"digest={digest}")
    typer.echo(f"smoke_response={snippet}")
    typer.echo(f"artifacts written to {run_dir}")


@app.command()
def run(  # noqa: CC102
    arm: Literal["A", "B"] = ARM_OPT,
    task_id: str = TASK_ID_OPT,
    repetition: int = REP_OPT,
    stage: Literal["smoke", "pilot"] = STAGE_OPT,
    enforce: Literal["N1", "N2", "N3", "N4"] = ENFORCE_OPT,
    model: str = MODEL_OPT,
    run_id: str = RUN_ID_OPT,
    use_cache: bool = USE_CACHE_OPT,
) -> None:
    """Run one experiment cell (arm, task, repetition)."""
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


@app.command()
def harvest(  # noqa: CC102
    harvest_dir: Path = HARVEST_DIR_OPT,
    arms: str = ARMS_OPT,
    repetitions: int = REPS_OPT,
    fail_on_missing: bool = FAIL_MISSING_OPT,
    skip_oracle: bool = SKIP_ORACLE_OPT,
    run_id: str = RUN_ID_OPT,
) -> None:
    """Merge cell outputs, re-run the oracle gate, and assert completeness."""
    parsed_arms = tuple(part.strip() for part in arms.split(",") if part.strip()) or ("A", "B")
    cfg = workflow_service.HarvestConfig(
        harvest_dir=harvest_dir,
        arms=parsed_arms,
        repetitions=repetitions,
        fail_on_missing=fail_on_missing,
        skip_oracle=skip_oracle,
        run_id=run_id,
    )
    try:
        summary_data = workflow_service.run_harvest(cfg)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(summary_data, indent=2, sort_keys=True))


@app.command()
def summary(harvest_dir: Path = HARVEST_DIR_OPT, run_id: str = RUN_ID_OPT) -> None:
    """Write the experiment step summary (artifacts, pins, completeness)."""
    markdown = workflow_summary.render_summary(harvest_dir=harvest_dir, run_id=run_id)
    typer.echo(markdown)


@app.command(name="backend-check")
def backend_check(  # noqa: CC102
    backend: str = BACKEND_OPT,
    ssh_host: str | None = SSH_HOST_OPT,
    control_path: Path | None = CONTROL_PATH_OPT,
    expected_digest: str | None = EXPECTED_DIGEST_OPT,
    model: str | None = OPT_MODEL_OPT,
    host: str | None = HOST_OPT,
    poll_timeout_s: float = POLL_TIMEOUT_OPT,
) -> None:
    """Verify remote-ollama SSH tunnel, poll /v1/models digest, and run one tiny completion."""
    cfg = backend_check_service.BackendCheckConfig(
        backend=backend,
        ssh_host=ssh_host,
        control_path=control_path,
        expected_digest=expected_digest,
        model=model,
        host=host,
        poll_timeout_s=poll_timeout_s,
    )
    try:
        result = backend_check_service.run_backend_check(cfg)
    except backend_check_service.BackendCheckError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(code=exc.exit_code) from exc
    backend_check_service.emit_github_outputs(result)
    typer.echo(
        f"{result.status} backend={result.backend} model={result.model} "
        f"digest={result.digest} base_url={result.base_url}"
    )
