"""Cell I/O adapter: paths, fixture staging, transcripts, deliverables, and Python sandbox."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from experiment.adapters import backends, paths, run_store, subprocess_runner
from experiment.domain.prompts import (
    RESULT_GEOJSON,
    RESULT_JSON,
    ChatTurn,
    SandboxExecution,
)

if TYPE_CHECKING:
    from experiment.domain.backend import BackendProfile
    from experiment.domain.task import Task

TASK_ROOT = paths.tasks_root()
RESULTS_ROOT = paths.results_root()

UTF8 = run_store.UTF8
JSON_INDENT = run_store.JSON_INDENT

ARM_PREFIX = "arm-"

DRIVERS = ("scripted", "ollama")
ARMS = ("A", "B")


def model_label(driver: str, model: str) -> str:
    return model if driver == "ollama" else "scripted-canned"


def fixture_path(task_path: Path, task: Task) -> Path:
    """The input fixture, resolved against the task file's directory."""
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
    return run_store.ensure_dir(path)


def cell_dir(output_root: Path, task_id: str, arm: str) -> Path:
    return run_store.ensure_dir(output_root / task_id / f"{ARM_PREFIX}{arm}")


def stage_fixture_input(task_path: Path, task: Task, cell: Path) -> Path:
    """Copy the task's fixture into ``cell/input.geojson`` for sandboxed Arm B runs."""
    target = cell / "input.geojson"
    target.write_bytes(fixture_path(task_path, task).read_bytes())
    return target


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
    """Minimal environment for sandboxed subprocesses."""
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


class FilesystemCellWorkspace:
    """Concrete ``CellWorkspace`` backed by the local cell directory."""

    def load_fixture(self, task_path: Path, task: Task) -> dict[str, Any]:
        return fixture_fc(task_path, task)

    def stage_fixture(self, task_path: Path, task: Task, cell: Path) -> Path:
        return stage_fixture_input(task_path, task, cell)

    def append_transcript(self, cell: Path, record: dict[str, Any]) -> None:
        append_transcript(cell, record)

    def write_deliverable(self, cell: Path, task: Task, payload: Any) -> Path:
        return write_deliverable(cell, task, payload)


class SubprocessCodeSandbox:
    """Concrete ``CodeSandbox`` executing Python in an isolated scrubbed subprocess."""

    def execute(self, code: str, cell: Path, timeout_s: int = 120) -> SandboxExecution:
        completed = run_python_sandboxed(code, cell, timeout_s=timeout_s)
        return SandboxExecution(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class HttpChatGateway:
    """Concrete ``ChatGateway`` over an OpenAI-compatible HTTP session."""

    def __init__(self, profile: BackendProfile) -> None:
        self._profile = profile
        self._session = backends.build_session(profile)

    @property
    def temperature(self) -> float:
        return self._profile.temperature

    @property
    def max_tokens(self) -> int:
        return self._profile.max_tokens

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return backends.chat_completions(self._session, self._profile, messages, tools)

    def parse_turn(self, reply: dict[str, Any]) -> ChatTurn:
        return backends.parse_chat_turn(reply)

    def close(self) -> None:
        self._session.close()
