"""Unit tests for ``experiment.adapters.qgis_env``."""

from __future__ import annotations

import sys
import types

import pytest

from experiment.adapters import qgis_env


def test_qgis_env_and_plugin_versions_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """``experiment.adapters.qgis_env`` and ``experiment_plugin._versions`` stay in sync."""
    from experiment_plugin import _versions as plugin_versions

    for key in ("QGIS_VERSION", "GDAL_VERSION", "GEOS_VERSION", "PROJ_VERSION"):
        monkeypatch.delenv(key, raising=False)

    core = types.ModuleType("qgis.core")

    class FakeQgis:
        @staticmethod
        def version() -> str:
            return "4.2.3-Belém do Pará"

        @staticmethod
        def geosVersion() -> str:
            return "3.14.1-CAPI-1.20.5"

    core.Qgis = FakeQgis
    osgeo_pkg = types.ModuleType("osgeo")
    gdal_mod = types.ModuleType("osgeo.gdal")
    gdal_mod.VersionInfo = lambda req="RELEASE_NAME": "3.13.3" if req == "RELEASE_NAME" else ""
    osr_mod = types.ModuleType("osgeo.osr")
    osr_mod.GetPROJVersionMajor = lambda: 9
    osr_mod.GetPROJVersionMinor = lambda: 9
    osr_mod.GetPROJVersionMicro = lambda: 0
    osgeo_pkg.gdal = gdal_mod
    osgeo_pkg.osr = osr_mod

    monkeypatch.setitem(sys.modules, "qgis.core", core)
    monkeypatch.setitem(sys.modules, "osgeo", osgeo_pkg)
    monkeypatch.setitem(sys.modules, "osgeo.gdal", gdal_mod)
    monkeypatch.setitem(sys.modules, "osgeo.osr", osr_mod)

    adapter_versions = qgis_env.probe_qgis_versions()
    host_versions = plugin_versions.host_software_versions()
    assert adapter_versions is not None
    for key in ("qgis", "gdal", "geos", "proj"):
        assert adapter_versions[key] == host_versions[key]
