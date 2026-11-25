"""Subprocess execution adapter: typed results, timeouts, and version probes."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CommandTimeoutError(RuntimeError):
    """A subprocess exceeded its wall-clock timeout."""


class CommandResult(BaseModel):
    """Typed subprocess outcome returned to services and CLI layers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def which(executable: str) -> str | None:
    """Locate ``executable`` on ``PATH``."""
    return shutil.which(executable)


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> CommandResult:
    """Run ``argv`` capturing stdout/stderr as text; raise CommandTimeoutError on timeout."""
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeoutError(f"command timed out after {timeout}s: {list(argv)}") from exc
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def run_passthrough(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> int:
    """Run ``argv`` inheriting stdio and return its exit code."""
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeoutError(f"command timed out after {timeout}s: {list(argv)}") from exc
    return completed.returncode


def soft_version(argv: Sequence[str], cwd: Path) -> str:
    """Probe a tool's first output line, returning ``'unavailable'`` if missing."""
    try:
        result = run_command(argv, cwd=cwd)
    except OSError:
        return "unavailable"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0].strip() if lines else "unavailable"


def run_python_script(
    script: Path,
    workdir: Path,
    *,
    env: Mapping[str, str],
    timeout_s: int,
) -> CommandResult:
    """Run ``script`` with an isolated Python interpreter (``-I``) and scrubbed env."""
    return run_command(
        [sys.executable, "-I", str(script.resolve())],
        cwd=workdir,
        env=env,
        timeout=timeout_s,
    )
