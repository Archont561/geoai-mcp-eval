"""Pilot cell execution helper backing ``workflow.run_workflow_cell(stage="pilot")``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from experiment.adapters import backends, paths, run_store
from experiment.adapters import ollama as ollama_adapter
from experiment.adapters.harness_io import CellRequest, append_transcript
from experiment.adapters.task_repository import find_task_file, load_task
from experiment.services import runs as runs_service

OLLAMA_API = ollama_adapter.DEFAULT_BASE_URL


@dataclass(frozen=True)
class WorkflowCellSpec:
    """Parameters for one workflow cell execution."""

    arm: Literal["A", "B"]
    task_id: str
    repetition: int = 1
    stage: Literal["smoke", "pilot"] = "smoke"
    enforce: Literal["N1", "N2", "N3", "N4"] = "N3"
    model: str = "qwen2.5:3b"
    run_id: str = ""
    use_cache: bool = False


def resolve_pilot_digest(ollama_bin: str, model: str) -> str | None:
    """Return the local Ollama model digest, pulling the model first if missing."""
    digest = ollama_adapter.list_model_digest(ollama_bin, model, base_url=OLLAMA_API)
    if digest and digest != "unknown":
        return digest
    rc = ollama_adapter.pull_model(ollama_bin, model)
    if rc != 0:
        raise RuntimeError(f"ollama pull {model} failed (exit {rc})")
    refreshed = ollama_adapter.list_model_digest(ollama_bin, model, base_url=OLLAMA_API)
    return refreshed if refreshed and refreshed != "unknown" else None


def _build_pilot_request(
    repo_root: Path,
    cell_dir: Path,
    spec: WorkflowCellSpec,
    run_id: str,
    digest: str | None,
) -> CellRequest:
    task_path = find_task_file(paths.tasks_root(repo_root), spec.task_id)
    profile = backends.resolve_profile(backends.LOCAL_BACKEND, host=OLLAMA_API, model=spec.model)
    return CellRequest(
        task_path=task_path,
        task=load_task(task_path),
        arm=spec.arm,
        driver="ollama",
        cell=cell_dir,
        model=profile.model,
        host=str(profile.base_url),
        run_id=run_id,
        profile=profile,
        backend_id=backends.LOCAL_BACKEND,
        model_digest=digest,
        use_cache=spec.use_cache,
        cache_dir=(repo_root / ".cache" / "llm") if spec.use_cache else None,
        enforce=spec.enforce,
        repetition=spec.repetition,
    )


def execute_pilot_cell(
    repo_root: Path,
    cell_dir: Path,
    spec: WorkflowCellSpec,
    base: dict[str, object],
    ollama_bin: str,
) -> dict[str, object]:
    """Run one pilot cell through ``runs.run_cell`` and return its manifest payload."""
    digest = resolve_pilot_digest(ollama_bin, spec.model)
    append_transcript(cell_dir, {"role": "meta", **base, "model_digest": digest})
    req = _build_pilot_request(repo_root, cell_dir, spec, str(base["run_id"]), digest)
    result = runs_service.run_cell(req)
    return {
        **base,
        "status": result["status"],
        "oracle_passed": result["oracle_passed"],
        "model_digest": digest,
        "usage": result["usage"],
        "wall_s": result["wall_s"],
        "error": result["error"],
        "artifacts": run_store.artifact_hashes(cell_dir),
    }
