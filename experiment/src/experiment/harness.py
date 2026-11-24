"""Shared plumbing for the prototype cells: paths, transcript, sandbox.

Everything both the run service (services/runs.py) and the drivers need,
kept dependency-free so it can be imported from either side without cycles.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from experiment.adapters import paths, run_store, subprocess_runner

if TYPE_CHECKING:
    from experiment.backends import BackendProfile
    from experiment.domain.cache_key import CacheStats
    from experiment.domain.task import Task
    from experiment.domain.usage import UsageAccumulator

TASK_ROOT = paths.tasks_root()
RESULTS_ROOT = paths.results_root()

RESULT_JSON = "result.json"
RESULT_GEOJSON = "result.geojson"

UTF8 = run_store.UTF8
JSON_INDENT = run_store.JSON_INDENT
_K_ROLE = "role"
_K_CONTENT = "content"
_K_ID = "id"

ARM_PREFIX = "arm-"

DRIVERS = ("scripted", "ollama")
ARMS = ("A", "B")


def model_label(driver: str, model: str) -> str:
    return model if driver == "ollama" else "scripted-canned"


@dataclass(frozen=True)
class RunSpec:
    """What to run: arms, task filter, driver, model, host.

    profile is the validated backend profile for the run (from backends.toml);
    None means "driver should synthesize one from host/model" (tests, ad-hoc runs).
    """

    arms: tuple[str, ...]
    task_ids: tuple[str, ...] | None
    driver: str
    model: str
    host: str
    profile: BackendProfile | None = None
    max_cell_tokens: int | None = None
    backend_id: str = "local"
    use_cache: bool = True
    cache_dir: Path | None = None


@dataclass(frozen=True)
class CellRequest:
    """Everything one (task, arm) cell needs; threaded through drivers."""

    task_path: Path
    task: Task
    arm: str
    driver: str
    cell: Path
    model: str
    host: str
    run_id: str
    profile: BackendProfile | None = None
    max_cell_tokens: int | None = None
    usage: UsageAccumulator | None = None
    backend_id: str = "local"
    model_digest: str | None = None
    use_cache: bool = True
    cache_dir: Path | None = None
    cache_stats: CacheStats | None = None


def fixture_path(task_path: Path, task: Task) -> Path:
    """The input fixture, resolved against the task file's directory.

    The model holds a *relative* path; joining it to the filesystem is the
    adapter's job, which keeps the domain value free of the filesystem.
    """
    path = (task_path.parent / task.fixture_input).resolve()
    if not path.is_file():
        raise ValueError(f"fixture not found: {path}")
    return path


def resolve_output_dir(output_dir: Path | None) -> Path:
    if output_dir is not None:
        path = output_dir
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = RESULTS_ROOT / f"prototype-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cell_dir(output_root: Path, task_id: str, arm: str) -> Path:
    path = output_root / task_id / f"{ARM_PREFIX}{arm}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_transcript(cell: Path, record: dict[str, Any]) -> None:
    run_store.append_jsonl(
        cell / "transcript.jsonl", {"ts": datetime.now(UTC).isoformat(), **record}
    )


def deliverable_name(task: Task) -> str:
    if any(a.get("output") == RESULT_GEOJSON for a in task.oracle.assertions):
        return RESULT_GEOJSON
    return RESULT_JSON


def write_deliverable(cell: Path, task: Task, payload: Any) -> Path:
    """Persist the cell's JSON/GeoJSON deliverable under the expected filename."""
    return run_store.write_json(cell / deliverable_name(task), payload, sort_keys=False)


def scrubbed_env(cell: Path, *, qt_platform: str | None = None) -> dict[str, str]:
    """Minimal environment for sandboxed subprocesses.

    qt_platform="offscreen" additionally sets QT_QPA_PLATFORM for hosts that
    import Qt (the PyQGIS sandbox); plain subprocesses leave it unset.
    """
    env = {
        "PATH": os.pathsep.join(
            [str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]
        ),
        "HOME": str(cell.resolve()),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
    }
    if qt_platform is not None:
        env["QT_QPA_PLATFORM"] = qt_platform
    return env


def run_python_sandboxed(
    code: str, cell: Path, timeout_s: int = 120
) -> subprocess_runner.CommandResult:
    return subprocess_runner.run_command(
        [sys.executable, "-I", "-c", code],
        cwd=cell,
        env=scrubbed_env(cell),
        timeout=timeout_s,
    )


def fixture_fc(task_path: Path, task: Task) -> dict[str, Any]:
    return run_store.read_json(fixture_path(task_path, task))


def extract_iso(features: list[dict[str, Any]]) -> list[str]:
    return [f["properties"]["ISO_A3"] for f in features]
