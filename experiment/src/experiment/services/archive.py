"""Service boundary for packing, inspecting, summarizing, and pruning RunArchives."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from experiment.adapters import paths, run_store
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.adapters.run_archive import RunArchive, build_artifact_refs, collect_dir_files
from experiment.adapters.task_repository import discover_task_files, load_task
from experiment.domain.run import (
    CostAndProcessMetrics,
    EnforcementLevel,
    EnvironmentPin,
    ExperimentRun,
    MeasurementContext,
    ModelPin,
    RunProvenance,
    RunStage,
    Treatment,
    TrialKey,
    TrialMeasurement,
    TrialRecord,
    arm_to_paradigm,
    parse_enforcement_level,
    parse_execution_status,
)
from experiment.services import archive_notices, workflow, workflow_summary
from experiment.services.measurement import TrialMeasurementOptions, measure_trial
from experiment.services.reports import ArchiveOverview, TrialOverview


class PackOptions(BaseModel):
    """Options for packing a run or harvest directory into one ``RunArchive`` zip."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_dir: Path
    output_zip: Path | None = None
    run_id: str = ""
    stage: RunStage = "pilot"
    arms: tuple[str, ...] = ("A", "B")
    repetitions: int = Field(default=2, ge=1)
    fail_on_missing: bool = False
    skip_oracle: bool = False
    run_harvest: bool = False


def _default_zip_path(source_dir: Path, run_id: str) -> Path:
    return source_dir.parent / f"experiment-run-{run_id}.zip"


def _read_environment_pin(source_dir: Path) -> EnvironmentPin:
    pins = run_store.read_env_pins(source_dir)
    return EnvironmentPin(
        repo_sha=pins.get("repo_sha"),
        pixi_lock_sha256=pins.get("pixi_lock_sha256"),
        python=pins.get("python"),
        ollama=pins.get("ollama"),
        qgis=pins.get("qgis"),
    )


def _read_model_pin(source_dir: Path) -> ModelPin | None:
    pin_file = run_store.find_first(source_dir, "model-digest.txt")
    if pin_file is None:
        return None
    parts = run_store.read_text(pin_file).strip().split()
    if not parts:
        return None
    digest = parts[1] if len(parts) >= 2 else None
    return ModelPin(backend_id="local", tag=parts[0], digest=digest)


def _trial_enforcement(arm: str, raw: object) -> EnforcementLevel:
    if arm != "A" or not isinstance(raw, str):
        return "none"
    try:
        return parse_enforcement_level(raw)
    except ValueError:
        return "none"


def _existing_measurement(cell_dir: Path) -> TrialMeasurement | None:
    score_doc = run_store.read_json_mapping(cell_dir / "score.json")
    if score_doc is None or not isinstance(score_doc.get("measurement"), dict):
        return None
    try:
        return TrialMeasurement.model_validate(score_doc["measurement"])
    except (ValidationError, ValueError, TypeError):
        return None


def _resolve_measurement(
    task_map: dict[str, Path],
    cell_dir: Path,
    record: TrialRecord,
    wall_s: float,
    existing: TrialMeasurement | None,
) -> TrialMeasurement:
    if existing is not None and existing.key == record.key:
        return existing
    task_path = task_map.get(record.key.task_id)
    if task_path is not None:
        opts = TrialMeasurementOptions(wall_seconds=wall_s)
        return measure_trial(task_path, cell_dir, key=record.key, options=opts)
    return TrialMeasurement.build(
        key=record.key,
        assertions=(),
        context=MeasurementContext(economics=CostAndProcessMetrics(wall_seconds=wall_s)),
    )


def _opt_str(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return str(value) if value else None


def _build_trial_record(
    key: TrialKey,
    manifest: dict[str, Any],
    payloads: dict[str, bytes],
) -> TrialRecord:
    driver = str(manifest.get("driver") or manifest.get("stage") or "scripted")
    treatment = Treatment(paradigm=key.paradigm, enforcement_level=key.enforcement_level)
    return TrialRecord(
        key=key,
        treatment=treatment,
        driver=driver,
        model_tag=_opt_str(manifest, "model"),
        model_digest=_opt_str(manifest, "model_digest"),
        status=parse_execution_status(manifest.get("status")),
        error=_opt_str(manifest, "error"),
        abort_reason=_opt_str(manifest, "abort_reason"),
        artifacts=build_artifact_refs(payloads),
    )


def _build_trial_key(
    cell: run_store.CellDir,
    manifest: dict[str, Any],
    existing: TrialMeasurement | None,
) -> TrialKey:
    enforce_raw = manifest.get("enforce") or (
        existing.key.enforcement_level if existing is not None else None
    )
    return TrialKey(
        task_id=cell.task_id,
        paradigm=arm_to_paradigm(cell.arm),
        enforcement_level=_trial_enforcement(cell.arm, enforce_raw),
        repetition=cell.repetition,
    )


def _build_trial_entry(
    task_map: dict[str, Path],
    cell: run_store.CellDir,
) -> tuple[TrialRecord, TrialMeasurement, dict[str, bytes]]:
    manifest = run_store.read_json_mapping(cell.path / "manifest.json") or {}
    existing = _existing_measurement(cell.path)
    key = _build_trial_key(cell, manifest, existing)
    payloads = collect_dir_files(cell.path)
    record = _build_trial_record(key, manifest, payloads)
    measurement = _resolve_measurement(
        task_map, cell.path, record, float(manifest.get("wall_s") or 0.0), existing
    )
    return record, measurement, payloads


def _collect_trials(
    source_dir: Path,
) -> tuple[dict[str, TrialRecord], dict[str, TrialMeasurement], dict[str, dict[str, bytes]]]:
    task_map = {load_task(p).id: p for p in discover_task_files(paths.tasks_root())}
    trials: dict[str, TrialRecord] = {}
    measurements: dict[str, TrialMeasurement] = {}
    payloads_map: dict[str, dict[str, bytes]] = {}
    for cell in run_store.discover_cells(source_dir):
        record, measurement, payloads = _build_trial_entry(task_map, cell)
        tid = record.trial_id
        trials[tid] = record
        measurements[tid] = measurement
        payloads_map[tid] = payloads
    return trials, measurements, payloads_map


def _maybe_run_harvest(source_dir: Path, rid: str, opts: PackOptions) -> RuntimeError | None:
    if not opts.run_harvest:
        return None
    try:
        workflow.run_harvest(
            workflow.HarvestConfig(
                harvest_dir=source_dir,
                arms=opts.arms,
                repetitions=opts.repetitions,
                fail_on_missing=opts.fail_on_missing,
                skip_oracle=opts.skip_oracle,
                run_id=rid,
            )
        )
    except RuntimeError as exc:
        return exc
    return None


def pack_archive(opts: PackOptions) -> tuple[ExperimentRun, Path]:
    """Pack a harvest or local run directory into a single ``RunArchive`` zip."""
    source_dir = opts.source_dir.resolve()
    rid = workflow.resolve_run_id(opts.run_id) if opts.run_id else source_dir.name
    harvest_error = _maybe_run_harvest(source_dir, rid, opts)
    trials, measurements, trial_payloads = _collect_trials(source_dir)
    provenance = RunProvenance(
        environment=_read_environment_pin(source_dir),
        model=_read_model_pin(source_dir),
    )
    run = ExperimentRun(
        run_id=rid,
        stage=opts.stage,
        created_at=datetime.now(UTC),
        provenance=provenance,
        trials=trials,
        measurements=measurements,
    )
    summary_md = workflow_summary.render_summary(harvest_dir=source_dir, run_id=rid)
    output_zip = opts.output_zip or _default_zip_path(source_dir, rid)
    RunArchive.write(output_zip, run, trial_files=trial_payloads, summary_markdown=summary_md)
    archive_notices.emit_ci_notices(run, trial_payloads)
    if harvest_error is not None:
        raise harvest_error
    return run, output_zip


def _trial_overview_row(m: TrialMeasurement) -> TrialOverview:
    return TrialOverview(
        trial_id=m.key.slug,
        task_id=m.key.task_id,
        paradigm=m.key.paradigm,
        enforcement_level=m.key.enforcement_level,
        repetition=m.key.repetition,
        task_success=m.outcomes.task_success,
        predicate_score=m.outcomes.predicate_score,
        silent_invalid=m.outcomes.silent_invalid,
    )


def _archive_metrics(items: list[TrialMeasurement], n_trials: int) -> tuple[int, float, float]:
    n_passed = sum(1 for m in items if m.outcomes.task_success)
    scores = [m.outcomes.predicate_score for m in items]
    mps = round((sum(scores) / len(scores)) if scores else 0.0, 4)
    tsr = (n_passed / n_trials) if n_trials else 0.0
    return n_passed, tsr, mps


def inspect_archive(archive_path: Path) -> ArchiveOverview:
    """Validate and return a structured overview of a ``RunArchive`` zip."""
    with RunArchive.open(archive_path) as archive:
        run = archive.run
        items = list(run.measurements.values())
        n_trials = len(run.trials)
        n_passed, tsr, mps = _archive_metrics(items, n_trials)
        model_pin = run.provenance.model
        trial_rows = tuple(_trial_overview_row(m) for m in items)
        return ArchiveOverview(
            run_id=run.run_id,
            stage=run.stage,
            schema_version=run.schema_version,
            model=model_pin.tag if model_pin else None,
            model_digest=model_pin.digest if model_pin else None,
            trial_count=n_trials,
            task_success_count=n_passed,
            task_success_rate=tsr,
            mean_predicate_score=mps,
            has_summary=archive.summary_markdown() is not None,
            trials=trial_rows,
        )


def render_summary(target: Path, run_id: str = "") -> str:
    """Render Markdown summary from a ``RunArchive`` zip or a harvest directory."""
    if run_store.is_file(target) and target.suffix == ".zip":
        with RunArchive.open(target) as archive:
            cached = archive.summary_markdown()
            if cached is not None:
                return cached
        overview = inspect_archive(target)
        return (
            f"# Experiment run `{overview.run_id}`\n\n"
            f"- Stage: `{overview.stage}`\n"
            f"- Trials: {overview.trial_count}\n"
            f"- Task Success Rate (TSR): {overview.task_success_rate:.2%}\n"
            f"- Mean Predicate Score (MPS): {overview.mean_predicate_score:.4f}\n"
        )
    return workflow_summary.render_summary(harvest_dir=target, run_id=run_id)


def prune_ci_artifacts(keep_name: str, run_id: str = "") -> list[str]:
    """Delete intermediate GitHub Actions artifacts for the run, keeping ``keep_name``."""
    return GitHubWorkflowAdapter().prune_run_artifacts(keep_name, run_id=run_id)
