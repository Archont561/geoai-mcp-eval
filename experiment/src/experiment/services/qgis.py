"""Probe PyQGIS and run scripts in the scrubbed subprocess sandbox."""

from __future__ import annotations

from pathlib import Path

from experiment.adapters import qgis_env, run_store, subprocess_runner
from experiment.adapters.harness_io import scrubbed_env
from experiment.adapters.subprocess_runner import CommandResult as SandboxRunResult


class ScriptNotFoundError(Exception):
    """The script path does not refer to a file."""


class QgisUnavailableError(Exception):
    """PyQGIS is not importable in the current interpreter."""


class SandboxTimeoutError(Exception):
    """The sandboxed subprocess exceeded its wall-clock limit."""


def qgis_versions() -> dict[str, str] | None:
    """Return interpreter versions, or None when PyQGIS is unavailable."""
    return qgis_env.probe_qgis_versions()


def prepare_script(script: Path, artifacts_dir: Path) -> None:
    """Check the script, create its working directory, and require PyQGIS."""
    if not run_store.is_file(script):
        raise ScriptNotFoundError(script)
    run_store.ensure_dir(artifacts_dir)
    if qgis_versions() is None:
        raise QgisUnavailableError()


def run_script(script: Path, artifacts_dir: Path, timeout_s: int) -> SandboxRunResult:
    """Run the checked script with an isolated interpreter and a scrubbed env."""
    try:
        return subprocess_runner.run_python_script(
            script,
            artifacts_dir,
            env=scrubbed_env(artifacts_dir, qt_platform="offscreen"),
            timeout_s=timeout_s,
        )
    except subprocess_runner.CommandTimeoutError as exc:
        raise SandboxTimeoutError() from exc
