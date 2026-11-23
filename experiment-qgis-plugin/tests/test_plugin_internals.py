"""Unit tests for the host-facing internals of the experiment plugin.

No display, no real QGIS: the QGIS host objects are faked with small doubles
(signals record slots, `crs()`/`fileName()`/`mapCanvas()` return sentinels),
and the lazy `qgis.core`/`qgis.utils` imports inside the functions are fed by
`monkeypatch.setitem(sys.modules, ...)`. The full host path is additionally
covered by the manual xvfb end-to-end run (see repo history / session notes);
these tests pin the logic itself.
"""

from __future__ import annotations

import sys
import types

import pytest

from experiment_plugin import plugin, session

# --- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_active_session(monkeypatch):
    plugin._ACTIVE["session"] = None
    plugin._LAST["session"] = None
    yield
    plugin._ACTIVE["session"] = None
    plugin._LAST["session"] = None


@pytest.fixture()
def task_suite(tmp_path, monkeypatch):
    (tmp_path / "demo-task-001.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: fixture.geojson\n", encoding="utf-8"
    )
    (tmp_path / "fixture.geojson").write_text("{}", encoding="utf-8")
    (tmp_path / "broken.yaml").write_text("{not: [valid", encoding="utf-8")
    # The panel starts sessions through the action, whose default base_dir is
    # $EXPERIMENT_TASK_DIR; point it at the suite so panel-started sessions find the task.
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def fake_project():
    """Fake QgsProject for project-hook tests (readProject variant, QGIS 4)."""

    class FakeSignal:
        def __init__(self) -> None:
            self.slots: list = []

        def connect(self, slot) -> None:
            self.slots.append(slot)

        def fire(self, *args) -> None:
            for slot in self.slots:
                slot(*args)

        def __call__(self, *args):  # PyQt bound signals are callable; mirror that
            self.fire(*args)

    class FakeCRS:
        @staticmethod
        def authid() -> str:
            return "EPSG:2180"

    class FakeProject:
        def __init__(self, read_signal_name: str | None = "readProject") -> None:
            self.layersAdded = FakeSignal()
            self.layersWillBeRemoved = FakeSignal()
            self.crsChanged = FakeSignal()
            if read_signal_name:
                setattr(self, read_signal_name, FakeSignal())
            self.fileName = lambda: "/tmp/fake-project.qgs"

        def crs(self):
            return FakeCRS()

    return FakeProject


@pytest.fixture()
def fake_canvas():
    class FakeSignal:
        def __init__(self) -> None:
            self.slots: list = []

        def connect(self, slot) -> None:
            self.slots.append(slot)

        def fire(self, *args) -> None:
            for slot in self.slots:
                slot(*args)

        def __call__(self, *args):  # PyQt bound signals are callable; mirror that
            self.fire(*args)

    class FakeExtent:
        def xMinimum(self):
            return 0.0

        def yMinimum(self):
            return 1.0

        def xMaximum(self):
            return 100.0

        def yMaximum(self):
            return 51.0

    class FakeCanvas:
        def __init__(self) -> None:
            self.extentsChanged = FakeSignal()
            self.scaleChanged = FakeSignal()

        def extent(self):
            return FakeExtent()

    return FakeCanvas


def _fake_qgis_modules(
    monkeypatch, project=None, iface=None, iface_raises: Exception | None = None
):
    core = types.ModuleType("qgis.core")

    class FakeQgsProject:
        @staticmethod
        def instance():
            if project is None:
                raise RuntimeError("project instance unavailable")
            return project

    core.QgsProject = FakeQgsProject

    utils = types.ModuleType("qgis.utils")
    if iface_raises is not None:

        class _Iface:
            @property
            def iface(self):
                raise iface_raises

        utils.__getattr__ = lambda name: (_ for _ in ()).throw(iface_raises)
    else:
        utils.iface = iface
    monkeypatch.setitem(sys.modules, "qgis.core", core)
    monkeypatch.setitem(sys.modules, "qgis.utils", utils)


def _start(task_suite) -> object:
    plugin._ACTIVE["session"] = None
    return plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))


# --- _task_dir / _active_session_error / _log_capped ------------------------


def test_task_dir_prefers_explicit_base_dir(task_suite, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", "/nowhere/else")
    assert plugin._task_dir("/explicit/dir") == "/explicit/dir"


def test_task_dir_uses_env_var_when_unset(task_suite, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", "/from/env")
    assert plugin._task_dir("") == "/from/env"


def test_task_dir_defaults_to_experiment_tasks(monkeypatch) -> None:
    monkeypatch.delenv("EXPERIMENT_TASK_DIR", raising=False)
    assert plugin._task_dir("") == "experiment/tasks"


def test_active_session_error_none_when_idle() -> None:
    assert plugin._active_session_error() is None


def test_active_session_error_reports_started_task(task_suite) -> None:
    plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    error = plugin._active_session_error()
    assert error is not None
    assert "demo-task-001" in error and "already active" in error
    plugin.end_session(None)


def test_log_capped_logs_below_cap() -> None:
    logged = []

    class _Tracker:
        event_count = plugin.MAX_EVENTS - 1

    class _Session:
        tracker = _Tracker()

        def log(self, event, tool=None, **fields):
            logged.append((event, tool, fields))

    plugin._log_capped(_Session(), "evt", "tool", key="value")
    assert logged == [("evt", "tool", {"key": "value"})]


def test_log_capped_swallows_at_cap() -> None:
    logged = []

    class _Tracker:
        event_count = plugin.MAX_EVENTS

    class _Session:
        tracker = _Tracker()

        def log(self, event, tool=None, **fields):
            logged.append((event, tool, fields))

    plugin._log_capped(_Session(), "evt", "tool")
    assert logged == []


# --- project / canvas hooks --------------------------------------------------


def test_connect_host_hooks_project_layer_partial(
    monkeypatch, task_suite, fake_project, fake_canvas
) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    project = fake_project(None)  # forces the project_read warning path
    iface = types.SimpleNamespace(mapCanvas=lambda c=fake_canvas: c())
    _fake_qgis_modules(monkeypatch, project=project, iface=iface)
    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == ["project (partial)", "canvas"]
    assert failures and "project_read" in failures[0]


def test_connect_host_hooks_project_import_failure(monkeypatch, task_suite) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    _fake_qgis_modules(monkeypatch, project=None, iface=None)
    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == []
    assert failures and failures[0].startswith("project:")


def test_start_message_lists_hooks_and_failures(task_suite) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    message = plugin._start_message(sess, ["canvas"], ["project_read: missing"])
    assert "host hooks: canvas" in message
    assert "host hook failed: project_read: missing" in message
    assert session.sha256_file(sess.task_yaml) in message


# --- action surface (hello/start/log/end) ------------------------------------


def test_find_task_yaml_reports_parse_errors(tmp_path) -> None:
    (tmp_path / "broken.yaml").write_text("{not: [valid", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as excinfo:
        session.find_task_yaml(tmp_path, "demo-task-001")
    assert "parse errors" in str(excinfo.value)


def test_host_software_versions_without_qgis(monkeypatch) -> None:
    monkeypatch.setenv("QGIS_VERSION", "9.9.9")
    monkeypatch.setitem(sys.modules, "qgis.core", None)  # `import qgis.core` -> ImportError
    versions = session.host_software_versions()
    assert versions["qgis"] == "9.9.9"


def test_session_log_without_tool_keeps_tools_empty(tmp_path) -> None:
    (tmp_path / "t.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: f.geojson\n", encoding="utf-8"
    )
    (tmp_path / "f.geojson").write_text("{}", encoding="utf-8")
    sess = session.start_session("demo-task-001", tmp_path)
    sess.log("bare_event")  # no tool: exercises the `tool is None` branch
    sess.log("tooled", tool="note")  # first time: appended
    sess.log("tooled_again", tool="note")  # already seen: not duplicated
    assert sess.tools_used == ["note"]


# --- panel formatting -------------------------------------------------------


def test_format_elapsed_pads_and_clamps() -> None:
    assert plugin._format_elapsed(0) == "00:00:00"
    assert plugin._format_elapsed(65) == "00:01:05"
    assert plugin._format_elapsed(3600 * 26 + 61) == "26:01:01"
    assert plugin._format_elapsed(-5) == "00:00:00"
