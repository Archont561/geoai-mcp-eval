"""Properties of plugin software-version recording."""

from __future__ import annotations

import sys

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment_plugin import _versions


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(version="9.9.9")
@given(version=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789. -", max_size=30))
def test_host_software_versions_without_qgis(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setenv("QGIS_VERSION", version)
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    versions = _versions.host_software_versions()
    assert versions["qgis"] == (version.strip() or None)
    assert _versions.host_identity()
