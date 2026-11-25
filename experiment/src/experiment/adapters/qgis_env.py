"""Host PyQGIS / GDAL / GEOS / PROJ version probing adapter.

Note: ``experiment-qgis-plugin/experiment_plugin/_versions.py`` intentionally
mirrors this version-probing logic so the QGIS plugin remains standalone when
installed outside this repository. ``test_qgis_service.py`` asserts parity
between both probers so they stay in lockstep.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import sys


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


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _format_proj_tuple(major: object, minor: object, micro: object = None) -> str | None:
    maj, min_ = _as_int(major), _as_int(minor)
    if maj is None or maj <= 0 or min_ is None:
        return None
    mic = _as_int(micro)
    suffix = f".{mic}" if mic is not None else ""
    return f"{maj}.{min_}{suffix}"


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


def probe_qgis_versions() -> dict[str, str] | None:
    """Return interpreter geospatial library versions, or None when PyQGIS is unavailable."""
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
