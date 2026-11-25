"""Host software version probing and non-identifying runtime identity.

Because ``experiment_plugin`` is packaged as a standalone QGIS plugin ZIP without
importing ``experiment``, this module mirrors the PyQGIS/GDAL/GEOS/PROJ probing
logic in ``experiment.adapters.qgis_env``; ``experiment/tests/test_qgis_service.py``
asserts behavioral parity between both implementations.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import platform


def _clean_version(value: object) -> str | None:
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


def _qgis_version(qgis_core: object) -> str | None:
    qgis_cls = getattr(qgis_core, "Qgis", None)
    return _clean_version(
        _safe_call(qgis_cls, "version")
        or getattr(qgis_cls, "QGIS_VERSION", None)
        or getattr(qgis_core, "QGIS_VERSION", None)
    )


def _geos_version(qgis_core: object) -> str | None:
    qgis_cls = getattr(qgis_core, "Qgis", None)
    return _clean_version(
        _safe_call(qgis_cls, "geosVersion") or getattr(qgis_core, "GEOS_VERSION", None)
    )


def _gdal_version(qgis_core: object) -> str | None:
    direct = _clean_version(getattr(qgis_core, "GDAL_VERSION", None))
    if direct is not None:
        return direct
    try:
        from osgeo import gdal  # type: ignore[import-not-found]
    except ImportError:
        return None
    return _clean_version(
        _safe_call(gdal, "VersionInfo", "RELEASE_NAME") or getattr(gdal, "__version__", None)
    )


def _proj_version(qgis_core: object) -> str | None:
    direct = _clean_version(getattr(qgis_core, "PROJ_VERSION", None))
    if direct is not None:
        return direct
    with contextlib.suppress(ImportError):
        from osgeo import osr  # type: ignore[import-not-found]

        formatted = _format_proj_tuple(
            _safe_call(osr, "GetPROJVersionMajor"),
            _safe_call(osr, "GetPROJVersionMinor"),
            _safe_call(osr, "GetPROJVersionMicro"),
        )
        if formatted is not None:
            return formatted
    proj_utils = getattr(qgis_core, "QgsProjUtils", None)
    return _format_proj_tuple(
        _safe_call(proj_utils, "projVersionMajor"),
        _safe_call(proj_utils, "projVersionMinor"),
    )


def host_software_versions() -> dict[str, str | None]:
    """Best-effort versions; each is None when the host did not say."""
    versions: dict[str, str | None] = {
        "qgis": _clean_version(os.environ.get("QGIS_VERSION")),
        "gdal": _clean_version(os.environ.get("GDAL_VERSION")),
        "geos": _clean_version(os.environ.get("GEOS_VERSION")),
        "proj": _clean_version(os.environ.get("PROJ_VERSION")),
    }
    try:  # PyQGIS hosts usually can answer properly
        qgis_core = importlib.import_module("qgis.core")
    except ImportError:
        return versions
    versions["qgis"] = versions["qgis"] or _qgis_version(qgis_core)
    versions["gdal"] = versions["gdal"] or _gdal_version(qgis_core)
    versions["geos"] = versions["geos"] or _geos_version(qgis_core)
    versions["proj"] = versions["proj"] or _proj_version(qgis_core)
    return versions


def host_identity() -> dict[str, str]:
    """Non-identifying environment facts (no hostname, no user name)."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
