"""Probe PyQGIS and run scripts in the scrubbed subprocess sandbox."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from experiment.harness import scrubbed_env


class ScriptNotFoundError(Exception):
    """The script path does not refer to a file."""


class QgisUnavailableError(Exception):
    """PyQGIS is not importable in the current interpreter."""


class SandboxTimeoutError(Exception):
    """The sandboxed subprocess exceeded its wall-clock limit."""


def qgis_versions() -> dict[str, str] | None:
    """Return interpreter versions, or None when PyQGIS is unavailable."""
    try:
        import qgis.core  # type: ignore[import-not-found]
    except ImportError:
        return None
    versions: dict[str, str] = {}
    try:
        versions["qgis"] = qgis.core.Qgis.QGIS_VERSION
    except AttributeError:
        versions["qgis"] = getattr(qgis.core, "QGIS_VERSION", "unknown")
    for key, attr in (("gdal", "GDAL_VERSION"), ("geos", "GEOS_VERSION"), ("proj", "PROJ_VERSION")):
        value = getattr(qgis.core, attr, None) or os.environ.get(f"{key.upper()}_VERSION")
        versions[key] = str(value) if value else "unknown"
    versions["python"] = sys.version.split()[0]
    return versions


def prepare_script(script: Path, artifacts_dir: Path) -> None:
    """Check the script, create its working directory, and require PyQGIS."""
    if not script.is_file():
        raise ScriptNotFoundError(script)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if qgis_versions() is None:
        raise QgisUnavailableError()


def run_script(
    script: Path, artifacts_dir: Path, timeout_s: int
) -> subprocess.CompletedProcess[str]:
    """Run the checked script with an isolated interpreter and a scrubbed env."""
    try:
        return subprocess.run(
            [sys.executable, "-I", str(script.resolve())],
            cwd=artifacts_dir,
            env=scrubbed_env(artifacts_dir, qt_platform="offscreen"),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxTimeoutError() from exc
