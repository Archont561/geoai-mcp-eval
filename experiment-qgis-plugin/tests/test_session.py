"""Unit tests for the recorder's rendering and hashing."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment_plugin import session


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(live="4.2.3-Live", legacy_qgis="3.40.1", override="3.10.0-override", major=9, minor=9)
@given(
    live=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", min_size=1, max_size=20),
    legacy_qgis=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", min_size=1, max_size=20),
    override=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", min_size=1, max_size=20),
    major=st.integers(min_value=1, max_value=99),
    minor=st.integers(min_value=0, max_value=99),
)
def test_host_software_versions_detects_qgis4_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    live: str,
    legacy_qgis: str,
    override: str,
    major: int,
    minor: int,
) -> None:
    for key in ("QGIS_VERSION", "GDAL_VERSION", "GEOS_VERSION", "PROJ_VERSION"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("QGIS_VERSION", "   ")
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    assert session.host_software_versions() == {
        "qgis": None,
        "gdal": None,
        "geos": None,
        "proj": None,
    }

    core = types.ModuleType("qgis.core")
    qgis_mock = MagicMock(name="Qgis")
    qgis_mock.QGIS_VERSION = "4.2.3-Fallback"
    qgis_mock.version.return_value = live
    qgis_mock.geosVersion.return_value = "3.14.1-CAPI-1.20.5"
    proj_mock = MagicMock(name="QgsProjUtils")
    proj_mock.projVersionMajor.return_value = major
    proj_mock.projVersionMinor.return_value = minor
    core.Qgis = qgis_mock  # type: ignore[attr-defined]
    core.QgsProjUtils = proj_mock  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "qgis.core", core)
    monkeypatch.setitem(sys.modules, "osgeo", None)
    monkeypatch.setitem(sys.modules, "osgeo.gdal", None)
    monkeypatch.setitem(sys.modules, "osgeo.osr", None)
    assert session.host_software_versions() == {
        "qgis": live,
        "gdal": None,
        "geos": "3.14.1-CAPI-1.20.5",
        "proj": f"{major}.{minor}",
    }

    legacy = types.ModuleType("qgis.core")
    legacy.QGIS_VERSION = legacy_qgis  # type: ignore[attr-defined]
    legacy.GDAL_VERSION = "3.9.2"  # type: ignore[attr-defined]
    legacy.GEOS_VERSION = "3.12.1"  # type: ignore[attr-defined]
    legacy.PROJ_VERSION = "9.4.0"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "qgis.core", legacy)
    monkeypatch.setenv("GDAL_VERSION", override)
    assert session.host_software_versions() == {
        "qgis": legacy_qgis,
        "gdal": override,
        "geos": "3.12.1",
        "proj": "9.4.0",
    }
