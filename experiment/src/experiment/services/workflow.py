"""Experiment pipeline services (preflight, model pin, cell smoke/pilot, harvest).

Pure service layer (no CLI/presentation framework imports, no direct transport
or subprocess I/O) backing ``experiment env|run|archive`` and Tasknest manifest
tasks declared in ``experiment/pyproject.toml``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from experiment.adapters import ollama as ollama_adapter
from experiment.adapters import paths, run_store, subprocess_runner
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.adapters.task_repository import discover_task_ids
from experiment.services import scoring as scoring_service
from experiment.services import tasks as tasks_service
from experiment.services import workflow_pilot
from experiment.services.workflow_pilot import WorkflowCellSpec

OLLAMA_API = ollama_adapter.DEFAULT_BASE_URL


def find_repo_root() -> Path:
    """Locate the repository root regardless of whether cwd is root or ``experiment/``."""
    return paths.find_repo_root()


def resolve_run_id(run_id: str) -> str:
    return GitHubWorkflowAdapter().resolve_run_id(run_id)


def _task_suite_root(repo_root: Path) -> Path:
    suite = paths.tasks_root(repo_root)
    return suite if run_store.is_dir(suite) else paths.tasks_root()


def _pilot_task_ids(repo_root: Path) -> tuple[str, ...]:
    suite = paths.tasks_root(repo_root)
    if run_store.is_dir(suite):
        discovered = discover_task_ids(suite)
        if discovered:
            return discovered
    return discover_task_ids(paths.tasks_root())


def run_preflight(run_id: str = "") -> tuple[str, dict[str, str], Path]:
    """Validate the pilot task suite and write ``results/<run_id>/env-pins.txt``."""
    repo_root = find_repo_root()
    rid = resolve_run_id(run_id)
    run_dir = run_store.ensure_dir(paths.results_root(repo_root) / rid)

    report = tasks_service.validate_suite(_task_suite_root(repo_root))
    if not report.passed:
        details = "; ".join(str(issue) for issue in report.issues)
        raise RuntimeError(f"pilot suite validation failed: {details}")

    lock = repo_root / "pixi.lock"
    pins = {
        "repo_sha": subprocess_runner.soft_version(["git", "rev-parse", "HEAD"], repo_root),
        "pixi_lock_sha256": run_store.sha256_file(lock) if run_store.exists(lock) else "missing",
        "python": subprocess_runner.soft_version([sys.executable, "--version"], repo_root),
        "ollama": subprocess_runner.soft_version(["ollama", "--version"], repo_root),
        "qgis": subprocess_runner.soft_version(["qgis", "--version"], repo_root),
    }
    pins_path = run_store.write_env_pins(run_dir / "env-pins.txt", pins)
    GitHubWorkflowAdapter().write_outputs({"run_id": rid, **pins})
    return rid, pins, pins_path


def _pull_and_smoke(ollama_bin: str, model: str, run_dir: Path) -> tuple[str, str]:
    if not ollama_adapter.wait_ready(OLLAMA_API):
        raise RuntimeError(
            f"ollama did not become ready at {OLLAMA_API}; see {run_dir / 'ollama-serve.log'}"
        )
    rc = ollama_adapter.pull_model(ollama_bin, model)
    if rc != 0:
        raise RuntimeError(f"ollama pull {model} failed (exit {rc})")
    digest = ollama_adapter.list_model_digest(ollama_bin, model, base_url=OLLAMA_API)
    run_store.write_text(run_dir / "model-digest.txt", f"{model} {digest}\n")
    payload = ollama_adapter.smoke_generate(model, base_url=OLLAMA_API)
    response_text = str(payload.get("response", "")).strip()
    if not response_text:
        raise RuntimeError("model returned an empty completion; pin or connectivity is broken")
    run_store.write_json(run_dir / "model-smoke.json", payload, indent=None)
    return digest, response_text[:80]


def run_model(model: str = "qwen2.5:3b", run_id: str = "") -> tuple[str, str, Path]:
    """Start Ollama, pull the pinned model, record digest, and prove one completion."""
    ollama_bin = subprocess_runner.which("ollama")
    if ollama_bin is None:
        raise RuntimeError(
            "ollama not on PATH. Install the locked pixi default environment "
            "(`pixi install --locked`, linux-64) — it ships ollama 0.32.* from conda-forge."
        )
    repo_root = find_repo_root()
    rid = resolve_run_id(run_id)
    run_dir = run_store.ensure_dir(paths.results_root(repo_root) / rid)
    owner = ollama_adapter.start_ollama(
        ollama_bin, run_dir / "ollama-serve.log", base_url=OLLAMA_API
    )
    try:
        digest, snippet = _pull_and_smoke(ollama_bin, model, run_dir)
    finally:
        ollama_adapter.stop_ollama(owner)
    GitHubWorkflowAdapter().write_outputs(
        {"run_id": rid, "model": model, "digest": digest, "smoke_response": snippet}
    )
    return digest, snippet, run_dir


def _write_cell_manifest(cell_dir: Path, record: dict[str, object]) -> None:
    run_store.write_json(cell_dir / "manifest.json", record, trailing_newline=True)


def _ensure_cell_ollama(
    ollama_bin: str | None, cell_dir: Path
) -> ollama_adapter.OllamaProcess | None:
    if ollama_bin is None:
        raise RuntimeError(
            "ollama not on PATH. Install the locked pixi default environment "
            "(`pixi install --locked`, linux-64) — the smoke stage exists to prove "
            "the model path works, so it must fail loudly without it."
        )
    owner = ollama_adapter.start_ollama(
        ollama_bin, cell_dir / "ollama-serve.log", base_url=OLLAMA_API
    )
    if owner is not None and not ollama_adapter.wait_ready(OLLAMA_API):
        ollama_adapter.stop_ollama(owner)
        raise RuntimeError("ollama did not become ready; see cell ollama-serve.log")
    return owner


def _run_pilot_cell(
    repo_root: Path,
    cell_dir: Path,
    spec: WorkflowCellSpec,
    base: dict[str, object],
    ollama_bin: str,
) -> None:
    manifest = workflow_pilot.execute_pilot_cell(repo_root, cell_dir, spec, base, ollama_bin)
    _write_cell_manifest(cell_dir, manifest)


def _run_smoke_probe(repo_root: Path, cell_dir: Path, base: dict[str, object]) -> None:
    discovered = tasks_service.list_tasks(_task_suite_root(repo_root))
    if not discovered:
        raise RuntimeError("smoke probe failed: no tasks discovered in suite")
    record_meta = {
        **base,
        "status": "mock-smoke",
        "note": "smoke probe only; NOT an agent run, NOT a study result",
        "ts": datetime.now(UTC).isoformat(),
    }
    run_store.append_jsonl(cell_dir / "transcript.jsonl", record_meta)
    _write_cell_manifest(
        cell_dir,
        {**base, "status": "mock-smoke", "artifacts": run_store.artifact_hashes(cell_dir)},
    )


def _cell_base_metadata(spec: WorkflowCellSpec, rid: str) -> dict[str, object]:
    return {
        "run_id": rid,
        "arm": spec.arm,
        "task": spec.task_id,
        "rep": spec.repetition,
        "stage": spec.stage,
        "model": spec.model,
        "enforce": spec.enforce if spec.arm == "A" else None,
    }


def run_workflow_cell(spec: WorkflowCellSpec) -> Path:
    """Run one (arm, task, repetition) cell for either smoke or pilot stage."""
    repo_root = find_repo_root()
    rid = resolve_run_id(spec.run_id)
    cell_dir = run_store.ensure_dir(
        run_store.cell_dir_path(
            paths.results_root(repo_root) / rid, spec.arm, spec.task_id, spec.repetition
        )
    )
    base = _cell_base_metadata(spec, rid)
    ollama_bin = subprocess_runner.which("ollama")
    owner: ollama_adapter.OllamaProcess | None = None
    try:
        owner = _ensure_cell_ollama(ollama_bin, cell_dir)
        if spec.stage == "pilot":
            assert ollama_bin is not None
            _run_pilot_cell(repo_root, cell_dir, spec, base, ollama_bin)
        else:
            _run_smoke_probe(repo_root, cell_dir, base)
        return cell_dir
    except Exception as exc:
        _write_cell_manifest(
            cell_dir, {**base, "status": "error", "error": str(exc), "artifacts": []}
        )
        raise
    finally:
        ollama_adapter.stop_ollama(owner)


class HarvestConfig(BaseModel):
    """Parameters for harvesting experiment cell outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    harvest_dir: Path = Path("harvest")
    arms: tuple[str, ...] = ("A", "B")
    repetitions: int = Field(default=2, ge=1)
    fail_on_missing: bool = True
    skip_oracle: bool = False
    run_id: str = ""


class _Comparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: set[tuple[str, str, int]]
    seen: set[tuple[str, str, int]]
    missing: list[tuple[str, str, int]]
    extra: list[tuple[str, str, int]]


def _cell_label(arm: str, task: str, rep: int) -> str:
    return f"{task}/{arm}/rep-{rep}"


def _valid_rep(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _load_manifest(path: Path) -> tuple[tuple[str, str, int], dict[str, object]] | None:
    record = run_store.read_json_mapping(path)
    if record is None:
        return None
    arm, task, rep = record.get("arm"), record.get("task"), record.get("rep")
    if isinstance(arm, str) and isinstance(task, str) and _valid_rep(rep):
        return (arm, task, rep), record
    return None


def _manifest_records(harvest_dir: Path) -> dict[tuple[str, str, int], dict[str, object]]:
    records: dict[tuple[str, str, int], dict[str, object]] = {}
    for path in run_store.discover_manifests(harvest_dir):
        loaded = _load_manifest(path)
        if loaded is not None:
            key, record = loaded
            records[key] = record
    return records


def _evaluate_cell(
    repo_root: Path,
    out_dir: Path,
    harvest: Path,
    cell_key: tuple[str, str, int],
    skip_oracle: bool,
) -> str:
    arm, task, rep = cell_key
    if skip_oracle:
        return "skipped(smoke)"
    cell_dir = run_store.find_cell_dir(harvest, arm, task, rep)
    if cell_dir is None:
        return "no-cell-dir"
    try:
        task_path, _ = tasks_service.get_task(task, _task_suite_root(repo_root))
        report = scoring_service.run_determinism_gate(task_path, cell_dir)
    except (tasks_service.TaskNotFoundError, OSError, ValueError) as exc:
        return f"error({exc})"
    run_store.write_json(out_dir / f"{task}-{arm}-rep{rep}.json", report.to_dict())
    return "pass" if report.passed else "fail"


def _compare_cells(
    records: dict[tuple[str, str, int], dict[str, object]],
    cfg: HarvestConfig,
    pilot_tasks: tuple[str, ...],
) -> _Comparison:
    expected = {
        (arm, task, rep)
        for arm in cfg.arms
        for task in pilot_tasks
        for rep in range(1, cfg.repetitions + 1)
    }
    seen = set(records)
    return _Comparison(
        expected=expected,
        seen=seen,
        missing=sorted(expected - seen),
        extra=sorted(seen - expected),
    )


def _build_harvest_summary(
    rid: str, comp: _Comparison, oracle: dict[str, str]
) -> dict[str, object]:
    return {
        "run_id": rid,
        "expected_cells": sorted(_cell_label(a, t, r) for a, t, r in comp.expected),
        "logged_cells": sorted(_cell_label(a, t, r) for a, t, r in comp.seen),
        "missing": [_cell_label(a, t, r) for a, t, r in comp.missing],
        "extra": [_cell_label(a, t, r) for a, t, r in comp.extra],
        "oracle": oracle,
        "complete": not comp.missing,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def run_harvest(cfg: HarvestConfig) -> dict[str, object]:
    """Merge cell manifests, run the oracle determinism gate, and check completeness."""
    repo_root = find_repo_root()
    rid = resolve_run_id(cfg.run_id)
    harvest = cfg.harvest_dir if cfg.harvest_dir.is_absolute() else (repo_root / cfg.harvest_dir)
    records = _manifest_records(harvest)
    run_store.write_jsonl(harvest / "manifest.jsonl", records.values())
    comp = _compare_cells(records, cfg, _pilot_task_ids(repo_root))
    out_dir = run_store.ensure_dir(harvest / "oracle")
    oracle = {
        _cell_label(a, t, r): _evaluate_cell(
            repo_root, out_dir, harvest, (a, t, r), cfg.skip_oracle
        )
        for a, t, r in sorted(comp.seen)
    }
    summary = _build_harvest_summary(rid, comp, oracle)
    run_store.write_json(harvest / "summary.json", summary)
    GitHubWorkflowAdapter().write_outputs(
        {"run_id": rid, "complete": not comp.missing, "missing_count": len(comp.missing)}
    )
    if comp.missing and cfg.fail_on_missing:
        missing_str = ", ".join(_cell_label(a, t, r) for a, t, r in comp.missing)
        raise RuntimeError(
            f"completeness assertion failed: {len(comp.missing)} missing run(s): "
            f"{missing_str} — never invented; fix the cells and re-run"
        )
    return summary
