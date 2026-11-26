"""RunArchive commands: pack, summary, inspect, and prune-ci."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from experiment.domain.run import RunStage
from experiment.services import archive as archive_service
from experiment.services import config as config_service

app = typer.Typer(help="Pack, summarize, inspect, and prune RunArchive zip bundles.")
console = Console(highlight=False)
_CFG = config_service.get_config()

HARVEST_DIR_OPT = typer.Option(
    Path("harvest"),
    "--harvest-dir",
    envvar="EXPERIMENT_HARVEST_DIR",
    help="Directory containing downloaded or local trial outputs",
)
OUTPUT_ZIP_OPT = typer.Option(
    None, "--output", envvar="EXPERIMENT_ARCHIVE_OUT", help="Output zip file path"
)
RUN_ID_OPT = typer.Option(
    "", "--run-id", envvar=["EXPERIMENT_RUN_ID", "RUN_ID"], help="Run identifier"
)
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable JSON")
ARMS_OPT = typer.Option("A,B", "--arms", envvar="EXPERIMENT_ARMS", help="Expected arms (e.g. A,B)")
REPS_OPT = typer.Option(2, "--repetitions", envvar="EXPERIMENT_REPETITIONS", help="Repetitions")
FAIL_MISSING_OPT = typer.Option(
    _CFG.archive.fail_on_missing,
    "--fail-on-missing/--no-fail-on-missing",
    envvar="EXPERIMENT_FAIL_ON_MISSING",
    help="Fail loudly when any expected trial is missing",
)
SKIP_ORACLE_OPT = typer.Option(
    _CFG.archive.skip_oracle,
    "--skip-oracle/--no-skip-oracle",
    envvar="EXPERIMENT_SKIP_ORACLE",
    help="Skip oracle determinism gate (smoke stage only)",
)
HARVEST_FLAG_OPT = typer.Option(
    True,
    "--harvest/--no-harvest",
    envvar="EXPERIMENT_RUN_HARVEST",
    help="Run harvest completeness/determinism gate before zipping",
)
STAGE_OPT = typer.Option(
    _CFG.experiment.default_stage,
    "--stage",
    envvar="EXPERIMENT_STAGE",
    help="Run stage (preflight|smoke|pilot|study)",
)
ARCHIVE_ARG = typer.Argument(..., help="Path to experiment-run-<run_id>.zip")
KEEP_OPT = typer.Option(
    ...,
    "--keep",
    envvar="EXPERIMENT_KEEP_ARTIFACT",
    help="Artifact name to retain when pruning CI handoff artifacts",
)
GH_RUN_ID_OPT = typer.Option(
    "",
    "--gh-run-id",
    envvar="GITHUB_RUN_ID",
    help="Numeric GitHub Actions run ID (defaults to $GITHUB_RUN_ID)",
)


def _emit_pack_report(run_id: str, stage: str, trial_count: int, zip_path: Path) -> None:
    payload = {
        "run_id": run_id,
        "stage": stage,
        "trial_count": trial_count,
        "archive_path": str(zip_path),
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def pack(  # noqa: CC102
    harvest_dir: Path = HARVEST_DIR_OPT,
    output: Path | None = OUTPUT_ZIP_OPT,
    run_id: str = RUN_ID_OPT,
    arms: str = ARMS_OPT,
    repetitions: int = REPS_OPT,
    fail_on_missing: bool = FAIL_MISSING_OPT,
    skip_oracle: bool = SKIP_ORACLE_OPT,
    run_harvest: bool = HARVEST_FLAG_OPT,
    stage: RunStage = STAGE_OPT,
) -> None:
    """Merge trial outputs into one validated RunArchive zip and render summary."""
    parsed_arms = tuple(p.strip() for p in arms.split(",") if p.strip()) or ("A", "B")
    opts = archive_service.PackOptions(
        source_dir=harvest_dir,
        output_zip=output,
        run_id=run_id,
        stage=stage,
        arms=parsed_arms,
        repetitions=repetitions,
        fail_on_missing=fail_on_missing,
        skip_oracle=skip_oracle,
        run_harvest=run_harvest,
    )
    try:
        run, zip_path = archive_service.pack_archive(opts)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _emit_pack_report(run.run_id, run.stage, len(run.trials), zip_path)


@app.command()
def summary(harvest_dir: Path = HARVEST_DIR_OPT, run_id: str = RUN_ID_OPT) -> None:
    """Render Markdown summary from a RunArchive zip or harvest directory."""
    markdown = archive_service.render_summary(harvest_dir, run_id=run_id)
    typer.echo(markdown)


@app.command()
def inspect(archive_path: Path = ARCHIVE_ARG, as_json: bool = JSON_OPTION) -> None:
    """Validate RunArchive integrity and print a Rich overview of trials and scores."""
    overview = archive_service.inspect_archive(archive_path)
    if as_json:
        typer.echo(json.dumps(overview.to_dict(), indent=2, sort_keys=True))
        return
    table = Table(
        title=f"RunArchive · {overview.run_id} ({overview.stage})",
        header_style="bold cyan",
    )
    for col in ("trial_id", "paradigm", "enforcement", "rep", "TSR", "MPS"):
        table.add_column(col)
    for row in overview.trials:
        tsr_cell = "1" if row.task_success else "0"
        mps_cell = f"{row.predicate_score:.2f}"
        table.add_row(
            row.trial_id,
            row.paradigm,
            row.enforcement_level,
            str(row.repetition),
            tsr_cell,
            mps_cell,
        )
    console.print(table)
    trials = overview.trial_count
    tsr = f"{overview.task_success_rate:.2%}"
    mps = f"{overview.mean_predicate_score:.4f}"
    console.print(Text(f"trials={trials}  TSR={tsr}  MPS={mps}", style="bold green"))


@app.command("prune-ci")
def prune_ci(keep: str = KEEP_OPT, gh_run_id: str = GH_RUN_ID_OPT) -> None:
    """Delete intermediate GitHub Actions artifacts for the current run except KEEP."""
    try:
        deleted = archive_service.prune_ci_artifacts(keep, run_id=gh_run_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({"kept": keep, "deleted": deleted}, indent=2))
