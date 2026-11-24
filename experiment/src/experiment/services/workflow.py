"""Experiment pipeline services (preflight, model pin, cell smoke/pilot, harvest).

Pure service layer (no CLI/presentation framework imports) backing
``experiment workflow ...`` and Tasknest manifest tasks declared in
``experiment/pyproject.toml``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from experiment.adapters.github_workflow import GitHubWorkflowAdapter

OLLAMA_API = "http://127.0.0.1:11434"
READY_ATTEMPTS = 60
READY_SLEEP_S = 2
PILOT_TASKS = ("analysis-de9im-001", "cartography-jenks-001", "prep-axis-order-001")


def find_repo_root() -> Path:
    """Locate the repository root regardless of whether cwd is root or ``experiment/``."""
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for candidate in (start, *start.parents):
            if (candidate / "tasknest.toml").is_file() or (candidate / "pixi.toml").is_file():
                return candidate
    return Path.cwd().resolve()


def resolve_run_id(run_id: str) -> str:
    return GitHubWorkflowAdapter().resolve_run_id(run_id)


def experiment_env(repo_root: Path) -> dict[str, str]:
    merged = os.environ.copy()
    src_roots = [
        repo_root / "experiment" / "src",
        repo_root / "experiment-qgis-plugin",
    ]
    merged["PYTHONPATH"] = os.pathsep.join(str(p) for p in src_roots)
    return merged


def serve_running() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_API}/api/version", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def wait_ready() -> bool:
    for _ in range(READY_ATTEMPTS):
        if serve_running():
            return True
        time.sleep(READY_SLEEP_S)
    return False


def _soft_version(argv: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return "unavailable"
    out = (result.stdout or result.stderr).strip().splitlines()
    return out[0].strip() if out else "unavailable"


def run_preflight(run_id: str = "") -> tuple[str, dict[str, str], Path]:
    """Validate the pilot task suite and write ``results/<run_id>/env-pins.txt``."""
    repo_root = find_repo_root()
    rid = resolve_run_id(run_id)
    run_dir = repo_root / "results" / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [sys.executable, "-m", "experiment", "pilot", "validate"],
        cwd=repo_root,
        env=experiment_env(repo_root),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pilot suite validation failed (exit {proc.returncode})")

    lock = repo_root / "pixi.lock"
    pins = {
        "repo_sha": _soft_version(["git", "rev-parse", "HEAD"], repo_root),
        "pixi_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
        if lock.exists()
        else "missing",
        "python": _soft_version([sys.executable, "--version"], repo_root),
        "ollama": _soft_version(["ollama", "--version"], repo_root),
        "qgis": _soft_version(["qgis", "--version"], repo_root),
    }
    pins_path = run_dir / "env-pins.txt"
    pins_path.write_text("".join(f"{k}={v}\n" for k, v in pins.items()), encoding="utf-8")
    GitHubWorkflowAdapter().write_outputs({"run_id": rid, **pins})
    return rid, pins, pins_path


def _start_ollama(ollama: str, serve_log: Path) -> subprocess.Popen[bytes] | None:
    if serve_running():
        return None
    handle = serve_log.open("wb")
    return subprocess.Popen(
        [ollama, "serve"],
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop_owner(owner: subprocess.Popen[bytes] | None) -> None:
    if owner is None:
        return
    owner.terminate()
    try:
        owner.wait(timeout=10)
    except subprocess.TimeoutExpired:
        owner.kill()


def _smoke_model(model: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=json.dumps(
            {
                "model": model,
                "prompt": "Reply with: OK",
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _model_digest(ollama: str, model: str) -> str:
    result = subprocess.run(
        [ollama, "list"], capture_output=True, text=True, check=False, timeout=60
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and (parts[0] == model or parts[0].startswith(model.split(":", 1)[0])):
            return parts[1] if len(parts) > 1 else "unavailable"
    return "unavailable"


def run_model(model: str = "qwen2.5:3b", run_id: str = "") -> tuple[str, str, Path]:
    """Start Ollama, pull the pinned model, record digest, and prove one completion."""
    ollama = shutil.which("ollama")
    if ollama is None:
        raise RuntimeError(
            "ollama not on PATH. Install the locked pixi default environment "
            "(`pixi install --locked`, linux-64) — it ships ollama 0.32.* from conda-forge."
        )
    repo_root = find_repo_root()
    rid = resolve_run_id(run_id)
    run_dir = repo_root / "results" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    serve_log = run_dir / "ollama-serve.log"

    owner = _start_ollama(ollama, serve_log)
    try:
        if not wait_ready():
            raise RuntimeError(f"ollama did not become ready at {OLLAMA_API}; see {serve_log}")
        pull = subprocess.run([ollama, "pull", model], timeout=1800, check=False)
        if pull.returncode != 0:
            raise RuntimeError(f"ollama pull {model} failed (exit {pull.returncode})")
        digest = _model_digest(ollama, model)
        (run_dir / "model-digest.txt").write_text(f"{model} {digest}\n", encoding="utf-8")
        payload = _smoke_model(model)
        response_text = str(payload.get("response", "")).strip()
        if not response_text:
            raise RuntimeError("model returned an empty completion; pin or connectivity is broken")
        (run_dir / "model-smoke.json").write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        snippet = response_text[:80]
        GitHubWorkflowAdapter().write_outputs(
            {"run_id": rid, "model": model, "digest": digest, "smoke_response": snippet}
        )
        return digest, snippet, run_dir
    finally:
        _stop_owner(owner)


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


def _write_cell_manifest(cell_dir: Path, record: dict[str, object]) -> None:
    cell_dir.joinpath("manifest.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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


def _ensure_cell_ollama(ollama: str | None, cell_dir: Path) -> subprocess.Popen[bytes] | None:
    if ollama is None:
        raise RuntimeError(
            "ollama not on PATH. Install the locked pixi default environment "
            "(`pixi install --locked`, linux-64) — the smoke stage exists to prove "
            "the model path works, so it must fail loudly without it."
        )
    owner = _start_ollama(ollama, cell_dir / "ollama-serve.log")
    if owner is not None and not wait_ready():
        owner.terminate()
        raise RuntimeError("ollama did not become ready; see cell ollama-serve.log")
    return owner


def run_workflow_cell(spec: WorkflowCellSpec) -> Path:
    """Run one (arm, task, repetition) cell smoke probe, or refuse unimplemented pilot stage."""
    repo_root = find_repo_root()
    rid = resolve_run_id(spec.run_id)
    cell_dir = repo_root / "results" / rid / spec.task_id / spec.arm / f"rep-{spec.repetition}"
    cell_dir.mkdir(parents=True, exist_ok=True)
    base: dict[str, object] = {
        "run_id": rid,
        "arm": spec.arm,
        "task": spec.task_id,
        "rep": spec.repetition,
        "stage": spec.stage,
        "model": spec.model,
        "enforce": spec.enforce if spec.arm == "A" else None,
    }
    owner: subprocess.Popen[bytes] | None = None
    try:
        if spec.stage == "pilot":
            cell_dir.joinpath("status.txt").write_text(
                "BLOCKED: `experiment run` harness is not implemented (pre-freeze).\n",
                encoding="utf-8",
            )
            _write_cell_manifest(cell_dir, {**base, "status": "harness-missing", "artifacts": []})
            raise SystemExit(
                "stage=pilot refused: the agent harness is not implemented yet "
                f"(expected command: `python -m experiment run --arm {spec.arm} "
                f"--task {spec.task_id} --model {spec.model} --enforce {spec.enforce} "
                f"--repetition {spec.repetition}`). Use stage=smoke until it lands; "
                "see docs/study/implementation.md."
            )
        owner = _ensure_cell_ollama(shutil.which("ollama"), cell_dir)
        proc = subprocess.run(
            [sys.executable, "-m", "experiment", "hello", "hello"],
            cwd=repo_root,
            env=experiment_env(repo_root),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"smoke hello check failed (exit {proc.returncode})")
        record_meta = {
            **base,
            "status": "mock-smoke",
            "note": "smoke probe only; NOT an agent run, NOT a study result",
            "ts": datetime.now(UTC).isoformat(),
        }
        with (cell_dir / "transcript.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record_meta, sort_keys=True) + "\n")
        _write_cell_manifest(
            cell_dir,
            {**base, "status": "mock-smoke", "artifacts": _artifact_hashes(cell_dir)},
        )
        return cell_dir
    except SystemExit:
        raise
    except Exception as exc:
        _write_cell_manifest(
            cell_dir, {**base, "status": "error", "error": str(exc), "artifacts": []}
        )
        raise
    finally:
        _stop_owner(owner)


@dataclass(frozen=True)
class HarvestConfig:
    """Parameters for harvesting experiment cell outputs."""

    harvest_dir: Path = Path("harvest")
    arms: tuple[str, ...] = ("A", "B")
    repetitions: int = 2
    fail_on_missing: bool = True
    skip_oracle: bool = False
    run_id: str = ""


class _Comparison(NamedTuple):
    expected: set[tuple[str, str, int]]
    seen: set[tuple[str, str, int]]
    missing: list[tuple[str, str, int]]
    extra: list[tuple[str, str, int]]


def _cell_label(arm: str, task: str, rep: int) -> str:
    return f"{task}/{arm}/rep-{rep}"


def _load_manifest(path: Path) -> tuple[tuple[str, str, int], dict[str, object]] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    arm = record.get("arm")
    task = record.get("task")
    rep = record.get("rep")
    if (
        isinstance(arm, str)
        and isinstance(task, str)
        and isinstance(rep, int)
        and not isinstance(rep, bool)
    ):
        return (arm, task, rep), record
    return None


def _manifest_records(harvest_dir: Path) -> dict[tuple[str, str, int], dict[str, object]]:
    records: dict[tuple[str, str, int], dict[str, object]] = {}
    for path in sorted(harvest_dir.rglob("manifest.json")):
        loaded = _load_manifest(path)
        if loaded is not None:
            key, record = loaded
            records[key] = record
    return records


def _find_cell_dir(harvest_dir: Path, arm: str, task: str, rep: int) -> Path | None:
    candidates = [
        harvest_dir / f"experiment-{arm}-{task}-rep{rep}",
        harvest_dir / task / arm / f"rep-{rep}",
        *harvest_dir.glob(f"experiment-{arm}-{task}-rep{rep}*"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


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
    cell_dir = _find_cell_dir(harvest, arm, task, rep)
    if cell_dir is None:
        return "no-cell-dir"
    cmd = [
        sys.executable,
        "-m",
        "experiment",
        "pilot",
        "determinism",
        task,
        "--artifacts-dir",
        str(cell_dir),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            env=experiment_env(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"error({exc})"
    (out_dir / f"{task}-{arm}-rep{rep}.json").write_text(
        result.stdout or result.stderr, encoding="utf-8"
    )
    return "pass" if result.returncode == 0 else f"fail(exit={result.returncode})"


def run_harvest(cfg: HarvestConfig) -> dict[str, object]:
    """Merge cell manifests, run the oracle determinism gate, and check completeness."""
    repo_root = find_repo_root()
    rid = resolve_run_id(cfg.run_id)
    harvest = cfg.harvest_dir if cfg.harvest_dir.is_absolute() else (repo_root / cfg.harvest_dir)
    records = _manifest_records(harvest)
    (harvest / "manifest.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records.values()),
        encoding="utf-8",
    )
    expected = {
        (arm, task, rep)
        for arm in cfg.arms
        for task in PILOT_TASKS
        for rep in range(1, cfg.repetitions + 1)
    }
    seen = set(records)
    comp = _Comparison(
        expected=expected,
        seen=seen,
        missing=sorted(expected - seen),
        extra=sorted(seen - expected),
    )
    out_dir = harvest / "oracle"
    out_dir.mkdir(parents=True, exist_ok=True)
    oracle = {
        _cell_label(a, t, r): _evaluate_cell(
            repo_root, out_dir, harvest, (a, t, r), cfg.skip_oracle
        )
        for a, t, r in sorted(comp.seen)
    }
    summary: dict[str, object] = {
        "run_id": rid,
        "expected_cells": sorted(_cell_label(a, t, r) for a, t, r in comp.expected),
        "logged_cells": sorted(_cell_label(a, t, r) for a, t, r in comp.seen),
        "missing": [_cell_label(a, t, r) for a, t, r in comp.missing],
        "extra": [_cell_label(a, t, r) for a, t, r in comp.extra],
        "oracle": oracle,
        "complete": not comp.missing,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (harvest / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    GitHubWorkflowAdapter().write_outputs(
        {
            "run_id": rid,
            "complete": not comp.missing,
            "missing_count": len(comp.missing),
        }
    )
    if comp.missing and cfg.fail_on_missing:
        raise RuntimeError(
            f"completeness assertion failed: {len(comp.missing)} missing run(s): "
            + ", ".join(_cell_label(a, t, r) for a, t, r in comp.missing)
            + " — never invented; fix the cells and re-run"
        )
    return summary
