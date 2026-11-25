"""Cell I/O adapter: paths, ephemeral temp-dir Python sandbox, transcripts, deliverables."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
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
SANDBOX_FIXTURE_NAME = "input.geojson"

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


def scrubbed_env(workdir: Path, *, qt_platform: str | None = None) -> dict[str, str]:
    """Minimal environment for sandboxed subprocesses."""
    env = {
        "PATH": os.pathsep.join(
            [str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]
        ),
        "HOME": str(workdir.resolve()),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
    }
    if qt_platform is not None:
        env["QT_QPA_PLATFORM"] = qt_platform
    return env


@contextmanager
def isolated_sandbox_dir(fixture_src: Path | None = None) -> Iterator[Path]:
    """Yield a fresh temporary directory containing only a copy of ``input.geojson``."""
    with tempfile.TemporaryDirectory(prefix="geoai-sandbox-") as tmp:
        sandbox = Path(tmp)
        if fixture_src is not None:
            shutil.copy2(fixture_src, sandbox / SANDBOX_FIXTURE_NAME)
        yield sandbox


def run_python_sandboxed(
    code: str,
    *,
    fixture_src: Path | None = None,
    timeout_s: int = 120,
) -> subprocess_runner.CommandResult:
    """Execute ``code`` in a fresh temporary directory with ``input.geojson`` staged."""
    with isolated_sandbox_dir(fixture_src) as sandbox_dir:
        return subprocess_runner.run_command(
            [sys.executable, "-I", "-c", code],
            cwd=sandbox_dir,
            env=scrubbed_env(sandbox_dir),
            timeout=timeout_s,
        )


def fixture_fc(task_path: Path, task: Task) -> dict[str, Any]:
    return run_store.read_json(fixture_path(task_path, task))


def extract_iso(features: list[dict[str, Any]]) -> list[str]:
    return [f["properties"]["ISO_A3"] for f in features]


class FilesystemCellWorkspace:
    """Concrete ``CellWorkspace`` backed by the local cell directory."""

    def resolve_fixture(self, task_path: Path, task: Task) -> Path:
        return fixture_path(task_path, task)

    def load_fixture(self, task_path: Path, task: Task) -> dict[str, Any]:
        return fixture_fc(task_path, task)

    def append_transcript(self, cell: Path, record: dict[str, Any]) -> None:
        append_transcript(cell, record)

    def write_deliverable(self, cell: Path, task: Task, payload: Any) -> Path:
        return write_deliverable(cell, task, payload)


class SubprocessCodeSandbox:
    """Concrete ``CodeSandbox`` running Python in an ephemeral ``TemporaryDirectory``."""

    def execute(
        self,
        code: str,
        *,
        fixture_src: Path | None = None,
        timeout_s: int = 120,
    ) -> SandboxExecution:
        completed = run_python_sandboxed(code, fixture_src=fixture_src, timeout_s=timeout_s)
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
