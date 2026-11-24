"""Probe PyQGIS and run scripts in the scrubbed subprocess sandbox."""

from __future__ import annotations

import contextlib
import importlib
import os
import sys
from pathlib import Path

from experiment.adapters import run_store, subprocess_runner
from experiment.adapters.subprocess_runner import CommandResult as SandboxRunResult
from experiment.harness import scrubbed_env


class ScriptNotFoundError(Exception):
    """The script path does not refer to a file."""


class QgisUnavailableError(Exception):
    """PyQGIS is not importable in the current interpreter."""


class SandboxTimeoutError(Exception):
    """The sandboxed subprocess exceeded its wall-clock limit."""


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_call(obj: object, method_name: str, *args: object) -> object:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return None
    with contextlib.suppress(Exception):
        return method(*args)
    return None


def _qgis_version(qgis_core: object) -> str:
    qgis_cls = getattr(qgis_core, "Qgis", None)
    return (
        _clean(
            _safe_call(qgis_cls, "version")
            or getattr(qgis_cls, "QGIS_VERSION", None)
            or getattr(qgis_core, "QGIS_VERSION", None)
        )
        or "unknown"
    )


def _geos_version(qgis_core: object) -> str:
    qgis_cls = getattr(qgis_core, "Qgis", None)
    return (
        _clean(
            _safe_call(qgis_cls, "geosVersion")
            or getattr(qgis_core, "GEOS_VERSION", None)
            or os.environ.get("GEOS_VERSION")
        )
        or "unknown"
    )


def _gdal_version(qgis_core: object) -> str:
    direct = _clean(getattr(qgis_core, "GDAL_VERSION", None) or os.environ.get("GDAL_VERSION"))
    if direct is not None:
        return direct
    try:
        gdal = importlib.import_module("osgeo.gdal")
    except ImportError:
        return "unknown"
    raw = _safe_call(gdal, "VersionInfo", "RELEASE_NAME") or getattr(gdal, "__version__", None)
    return _clean(raw) or "unknown"


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _format_proj_tuple(major: object, minor: object, micro: object = None) -> str | None:
    maj, min_ = _as_int(major), _as_int(minor)
    if maj is None or maj <= 0 or min_ is None:
        return None
    mic = _as_int(micro)
    suffix = f".{mic}" if mic is not None else ""
    return f"{maj}.{min_}{suffix}"


def _proj_version(qgis_core: object) -> str:
    direct = _clean(getattr(qgis_core, "PROJ_VERSION", None) or os.environ.get("PROJ_VERSION"))
    if direct is not None:
        return direct
    with contextlib.suppress(ImportError):
        osr = importlib.import_module("osgeo.osr")
        formatted = _format_proj_tuple(
            _safe_call(osr, "GetPROJVersionMajor"),
            _safe_call(osr, "GetPROJVersionMinor"),
            _safe_call(osr, "GetPROJVersionMicro"),
        )
        if formatted is not None:
            return formatted
    proj_utils = getattr(qgis_core, "QgsProjUtils", None)
    formatted = _format_proj_tuple(
        _safe_call(proj_utils, "projVersionMajor"),
        _safe_call(proj_utils, "projVersionMinor"),
    )
    return formatted or "unknown"


def qgis_versions() -> dict[str, str] | None:
    """Return interpreter versions, or None when PyQGIS is unavailable."""
    if "qgis" in sys.modules and sys.modules["qgis"] is None:
        return None
    try:
        qgis_core = importlib.import_module("qgis.core")
    except ImportError:
        return None
    return {
        "qgis": _qgis_version(qgis_core),
        "gdal": _gdal_version(qgis_core),
        "geos": _geos_version(qgis_core),
        "proj": _proj_version(qgis_core),
        "python": sys.version.split()[0],
    }


def prepare_script(script: Path, artifacts_dir: Path) -> None:
    """Check the script, create its working directory, and require PyQGIS."""
    if not script.is_file():
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
