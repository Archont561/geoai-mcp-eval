"""Unit tests for ``experiment_plugin._versions``."""

from __future__ import annotations

import sys

import pytest

from experiment_plugin import _versions


def test_host_software_versions_without_qgis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QGIS_VERSION", "9.9.9")
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    versions = _versions.host_software_versions()
    assert versions["qgis"] == "9.9.9"
    assert _versions.host_identity()
