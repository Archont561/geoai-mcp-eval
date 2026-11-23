"""Unit-level tests for the `experiment qgis` sub-application.

The `proto` commands (ops, mcp-selftest, run, score, show) are specified in
``features/prototype-runs.feature`` and driven through the whole application.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from experiment.cli import qgis

RUN_CMD = "run"

runner = CliRunner()


def test_qgis_check_exits_3_without_pyqgis() -> None:
    if qgis._qgis_versions() is not None:
        pytest.skip("PyQGIS is importable here; exit-3 path not applicable")
    result = runner.invoke(qgis.app, ["check"])
    # No PyQGIS in this interpreter: by design exit 3 with remediation.
    assert result.exit_code == 3
    assert "PyQGIS unavailable" in result.output


def test_qgis_run_missing_script(tmp_path: Path) -> None:
    result = runner.invoke(qgis.app, [RUN_CMD, str(tmp_path / "nope.py")])
    assert result.exit_code == 2


def test_qgis_run_without_pyqgis(tmp_path: Path) -> None:
    if qgis._qgis_versions() is not None:
        pytest.skip("PyQGIS is importable here; exit-3 path not applicable")
    script = tmp_path / "s.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    result = runner.invoke(
        qgis.app, [RUN_CMD, str(script), "--artifacts-dir", str(tmp_path / "art")]
    )
    assert result.exit_code == 3


def test_qgis_versions_none_without_pyqgis() -> None:
    if qgis._qgis_versions() is not None:
        pytest.skip("PyQGIS is importable here; the no-PyQGIS path not applicable")
    assert qgis._qgis_versions() is None


def test_qgis_run_success_with_mocked_pyqgis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        qgis,
        "_qgis_versions",
        lambda: {"qgis": "4.2", "gdal": "x", "geos": "y", "proj": "z", "python": "3.13"},
    )
    script = tmp_path / "ok.py"
    script.write_text("print('hello-sandbox')\n", encoding="utf-8")
    result = runner.invoke(
        qgis.app, ["run", str(script), "--artifacts-dir", str(tmp_path / "art"), "--timeout", "30"]
    )
    assert result.exit_code == 0
    assert "hello-sandbox" in result.output


def test_qgis_run_nonzero_exit_propagates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        qgis,
        "_qgis_versions",
        lambda: {"qgis": "4.2", "gdal": "x", "geos": "y", "proj": "z", "python": "3.13"},
    )
    script = tmp_path / "fail.py"
    script.write_text(
        "import sys\nprint('out')\nprint('err', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8"
    )
    result = runner.invoke(
        qgis.app, [RUN_CMD, str(script), "--artifacts-dir", str(tmp_path / "art")]
    )
    assert result.exit_code == 7
    assert "err" in result.output


def test_qgis_run_timeout_exits_4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        qgis,
        "_qgis_versions",
        lambda: {"qgis": "4.2", "gdal": "x", "geos": "y", "proj": "z", "python": "3.13"},
    )

    def slow_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(qgis.subprocess, "run", slow_run)
    script = tmp_path / "slow.py"
    script.write_text("print('never')\n", encoding="utf-8")
    result = runner.invoke(
        qgis.app, ["run", str(script), "--artifacts-dir", str(tmp_path / "art"), "--timeout", "1"]
    )
    assert result.exit_code == 4


def test_qgis_check_available_with_mocked_pyqgis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qgis,
        "_qgis_versions",
        lambda: {"qgis": "4.2", "gdal": "x", "geos": "y", "proj": "z", "python": "3.13"},
    )
    result = runner.invoke(qgis.app, ["check"])
    assert result.exit_code == 0
    assert "available" in result.output
