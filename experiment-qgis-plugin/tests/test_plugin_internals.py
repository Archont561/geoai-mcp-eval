"""Unit tests for the host-facing internals of the experiment plugin."""

from __future__ import annotations

import sys
import types
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from plugin_harness import install_fake_qt

from experiment_plugin import plugin, session


def test_fake_qt_isolates_preloaded_qgis_host_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("qgis.core", "qgis.gui", "qgis.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    install_fake_qt(monkeypatch)
    for name in ("qgis.core", "qgis.gui", "qgis.utils"):
        with pytest.raises(ModuleNotFoundError):
            import_module(name)


@pytest.fixture(autouse=True)
def _clean_active_session() -> None:
    plugin._ACTIVE["session"] = None
    plugin._LAST["session"] = None
    yield
    plugin._ACTIVE["session"] = None
    plugin._LAST["session"] = None


@pytest.fixture
def task_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "demo-task-001.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: fixture.geojson\n", encoding="utf-8"
    )
    (tmp_path / "fixture.geojson").write_text("{}", encoding="utf-8")
    (tmp_path / "broken.yaml").write_text("{not: [valid", encoding="utf-8")
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_project() -> MagicMock:
    """``MagicMock`` QgsProject missing ``readProject`` (exercises partial-hook warning)."""
    project = MagicMock(name="QgsProjectInstance")
    del project.readProject
    del project.projectRead
    project.fileName.return_value = "/tmp/fake-project.qgs"
    project.crs.return_value.authid.return_value = "EPSG:2180"
    return project


@pytest.fixture
def fake_canvas() -> MagicMock:
    """``MagicMock`` QgsMapCanvas with extent coordinates and signal attributes."""
    canvas = MagicMock(name="QgsMapCanvas")
    extent = MagicMock(name="QgsRectangle")
    extent.xMinimum.return_value = 0.0
    extent.yMinimum.return_value = 1.0
    extent.xMaximum.return_value = 100.0
    extent.yMaximum.return_value = 51.0
    canvas.extent.return_value = extent
    return canvas


def test_task_dir_prefers_explicit_base_dir(
    task_suite: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", "/nowhere/else")
    assert plugin._task_dir("/explicit/dir") == "/explicit/dir"


def test_task_dir_uses_env_var_when_unset(
    task_suite: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", "/from/env")
    assert plugin._task_dir("") == "/from/env"


def test_task_dir_defaults_to_discovered_experiment_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXPERIMENT_TASK_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    resolved = Path(plugin._task_dir(""))
    assert resolved == session.discover_task_dir()
    assert resolved.parts[-2:] == ("experiment", "tasks")
    assert resolved.is_dir()


def test_active_session_error_none_when_idle() -> None:
    assert plugin._active_session_error() is None


def test_active_session_error_reports_started_task(task_suite: Path) -> None:
    plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    error = plugin._active_session_error()
    assert error is not None
    assert "demo-task-001" in error and "already active" in error
    plugin.end_session(None)


def test_log_capped_logs_below_cap() -> None:
    mock_session = MagicMock()
    mock_session.tracker.event_count = plugin.MAX_EVENTS - 1
    plugin._log_capped(mock_session, "evt", "host:project", key="value")
    mock_session.log.assert_called_once_with("evt", source="host:project", key="value")


def test_log_capped_swallows_at_cap() -> None:
    mock_session = MagicMock()
    mock_session.tracker.event_count = plugin.MAX_EVENTS
    plugin._log_capped(mock_session, "evt", "host:project")
    mock_session.log.assert_not_called()


def test_connect_host_hooks_project_layer_partial(
    task_suite: Path,
    fake_qgis_modules: MagicMock,
    fake_project: MagicMock,
    fake_canvas: MagicMock,
) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    fake_qgis_modules.QgsProject.instance.side_effect = None
    fake_qgis_modules.QgsProject.instance.return_value = fake_project
    iface = MagicMock(name="QgisInterface")
    iface.mapCanvas.return_value = fake_canvas
    fake_qgis_modules.utils.iface = iface

    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == ["project (partial)", "canvas"]
    assert failures and "project_read" in failures[0]


def test_connect_host_hooks_project_import_failure(
    task_suite: Path,
    fake_qgis_modules: MagicMock,
) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == []
    assert failures and failures[0].startswith("project:")


def test_start_message_lists_hooks_and_failures(task_suite: Path) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    message = plugin._start_message(sess, ["canvas"], ["project_read: missing"])
    assert "host hooks: canvas" in message
    assert "host hook failed: project_read: missing" in message
    assert session.sha256_file(sess.task_yaml) in message


def test_find_task_yaml_reports_parse_errors(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("{not: [valid", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as excinfo:
        session.find_task_yaml(tmp_path, "demo-task-001")
    assert "parse errors" in str(excinfo.value)


def test_host_software_versions_without_qgis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QGIS_VERSION", "9.9.9")
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    versions = session.host_software_versions()
    assert versions["qgis"] == "9.9.9"


def test_session_log_tracks_observation_sources_not_study_tools(tmp_path: Path) -> None:
    (tmp_path / "t.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: f.geojson\n", encoding="utf-8"
    )
    (tmp_path / "f.geojson").write_text("{}", encoding="utf-8")
    sess = session.start_session("demo-task-001", tmp_path)
    sess.log("bare_event")
    sess.log("noted", source="note")
    sess.log("noted_again", source="note")
    assert sess.metrics.observation_sources == ["note"]
    assert sess.metrics.raw_event_count == 3
    assert sess.metrics.processing_tools() is None


@given(seconds=st.integers(min_value=-1000, max_value=200_000))
def test_format_elapsed_pads_and_clamps(seconds: int) -> None:
    formatted = plugin._format_elapsed(seconds)
    parts = formatted.split(":")
    assert len(parts) == 3
    hours, minutes, secs = (int(p) for p in parts)
    assert len(parts[1]) == 2 and len(parts[2]) == 2
    assert 0 <= minutes < 60 and 0 <= secs < 60
    clamped = max(0, seconds)
    assert hours * 3600 + minutes * 60 + secs == clamped
