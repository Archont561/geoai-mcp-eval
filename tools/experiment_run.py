"""Run one (arm, task, repetition) cell of the experiment, or a pre-harness smoke probe."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NamedTuple

from tasknest import ToolContext, tool

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)  # tasknest execs by path; sibling helpers need tools/
from _experiment_common import (  # noqa: E402
    experiment_env,
    resolve_run_id,
    serve_running,
    wait_ready,
)

EXIT_HARNESS_MISSING = 64


class _CellSpec(NamedTuple):
    arm: str
    task_id: str
    repetition: int


def _write_cell_manifest(cell_dir: Path, record: dict[str, object]) -> None:
    cell_dir.joinpath("manifest.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _cell_dir(ctx: ToolContext, rid: str, spec: _CellSpec) -> Path:
    cell_dir = ctx.repo_root / "results" / rid / spec.task_id / spec.arm / f"rep-{spec.repetition}"
    cell_dir.mkdir(parents=True, exist_ok=True)
    return cell_dir


def _refuse_pilot_stage(
    cell_dir: Path,
    base: dict[str, object],
    spec: _CellSpec,
    model: str,
    enforce: str,
) -> None:
    cell_dir.joinpath("status.txt").write_text(
        "BLOCKED: `experiment run` harness is not implemented (pre-freeze).\n",
        encoding="utf-8",
    )
    _write_cell_manifest(cell_dir, {**base, "status": "harness-missing", "artifacts": []})
    raise SystemExit(
        "stage=pilot refused: the agent harness is not implemented yet "
        f"(expected command: `python -m experiment run --arm {spec.arm} --task {spec.task_id} "
        f"--model {model} --enforce {enforce} --repetition {spec.repetition}`). "
        "Use stage=smoke until it lands; see docs/study/implementation.md."
    )


def _ensure_ollama(ollama: str | None, cell_dir: Path) -> subprocess.Popen[bytes] | None:
    if ollama is None:
        raise RuntimeError(
            "ollama not on PATH. Install the locked pixi default environment "
            "(`pixi install --locked`, linux-64) — the smoke stage exists to prove "
            "the model path works, so it must fail loudly without it."
        )
    if serve_running():
        return None
    serve_log = cell_dir / "ollama-serve.log"
    owner = subprocess.Popen(
        [ollama, "serve"],
        stdout=serve_log.open("wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    if not wait_ready():
        owner.terminate()
        raise RuntimeError("ollama did not become ready; see cell ollama-serve.log")
    return owner


def _stop_owner(owner: subprocess.Popen[bytes] | None) -> None:
    if owner is None:
        return
    owner.terminate()
    try:
        owner.wait(timeout=10)
    except subprocess.TimeoutExpired:
        owner.kill()


def _artifact_hashes(cell_dir: Path) -> list[dict[str, object]]:
    cell_files = sorted(p for p in cell_dir.rglob("*") if p.is_file())
    return [
        {
            "path": str(p.relative_to(cell_dir)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
        for p in cell_files
    ]


def _run_smoke_probe(
    ctx: ToolContext,
    cell_dir: Path,
    base: dict[str, object],
    spec: _CellSpec,
) -> None:
    ctx.run(
        [sys.executable, "-m", "experiment", "hello", "hello"],
        env=experiment_env(ctx),
    )
    record_meta = {
        **base,
        "status": "mock-smoke",
        "note": "smoke probe only; NOT an agent run, NOT a study result",
        "ts": datetime.now(UTC).isoformat(),
    }
    with (cell_dir / "transcript.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record_meta, sort_keys=True) + "\n")
    artifacts = _artifact_hashes(cell_dir)
    _write_cell_manifest(cell_dir, {**base, "status": "mock-smoke", "artifacts": artifacts})
    print(f"cell complete: arm={spec.arm} task={spec.task_id} rep={spec.repetition} -> {cell_dir}")


def _record_error(cell_dir: Path, base: dict[str, object], exc: Exception) -> None:
    _write_cell_manifest(cell_dir, {**base, "status": "error", "error": str(exc), "artifacts": []})


def _base_manifest(
    rid: str, spec: _CellSpec, stage: str, model: str, enforce: str
) -> dict[str, object]:
    return {
        "run_id": rid,
        "arm": spec.arm,
        "task": spec.task_id,
        "rep": spec.repetition,
        "stage": stage,
        "model": model,
        "enforce": enforce if spec.arm == "A" else None,
    }


# The flat parameter list is the tasknest CLI contract; grouping would break it.
@tool(
    description="Run one experiment cell (arm, task, repetition).",
    marks=["ci", "workflow"],
)
def experiment_run(  # noqa: CC102
    ctx: ToolContext,
    arm: Literal["A", "B"],
    task_id: str,
    repetition: int = 1,
    stage: Literal["smoke", "pilot"] = "smoke",
    enforce: Literal["N1", "N2", "N3", "N4"] = "N3",
    model: str = "qwen2.5:3b",
    run_id: str = "",
) -> None:
    """Run one experiment cell (arm, task, repetition)."""
    spec = _CellSpec(arm=arm, task_id=task_id, repetition=repetition)
    rid = resolve_run_id(run_id)
    cell_dir = _cell_dir(ctx, rid, spec)
    base = _base_manifest(rid, spec, stage, model, enforce)
    owner: subprocess.Popen[bytes] | None = None
    try:
        # Smoke proves the wiring (CLI + Ollama + manifest plumbing). Pilot is the
        # real agent run and does not exist yet — fail loudly, never silently.
        if stage == "pilot":
            _refuse_pilot_stage(cell_dir, base, spec, model, enforce)
        owner = _ensure_ollama(shutil.which("ollama"), cell_dir)
        _run_smoke_probe(ctx, cell_dir, base, spec)
    except SystemExit:
        raise
    except Exception as exc:
        _record_error(cell_dir, base, exc)
        raise
    finally:
        _stop_owner(owner)
