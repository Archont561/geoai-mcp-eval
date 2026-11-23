"""Unit tests for the host-facing internals of the experiment plugin.

No display, no real QGIS: the QGIS host objects are faked with small doubles
(signals record slots, `crs()`/`fileName()`/`mapCanvas()` return sentinels),
and the lazy `qgis.core`/`qgis.utils` imports inside the functions are fed by
`monkeypatch.setitem(sys.modules, ...)`. The full host path is additionally
covered by the manual xvfb end-to-end run (see repo history / session notes);
these tests pin the logic itself.
"""

from __future__ import annotations

import json
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


def test_project_hooks_connect_and_fire(monkeypatch, task_suite, fake_project) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    message = plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    assert "session started" in message
    sess = plugin._ACTIVE["session"]
    project = fake_project("readProject")
    warnings = plugin._wire_project_hooks(sess, project)
    assert warnings == []
    project.layersAdded.fire(["a", "b"])
    project.layersWillBeRemoved.fire(["a"])
    project.crsChanged.fire()
    project.readProject.fire()
    record_path = plugin.end_session(None)
    events = (sess.output_dir / "events.jsonl").read_text().splitlines()
    parsed = [json.loads(line) for line in events]
    by_event = {entry["event"]: entry for entry in parsed}
    assert by_event["layers_added"]["count"] == 2
    assert by_event["layers_removed"]["count"] == 1
    assert by_event["crs_changed"]["crs"] == "EPSG:2180"
    assert by_event["project_read"]["path"] == "/tmp/fake-project.qgs"
    assert "record written" in record_path


def test_project_hooks_qgis3_signal_fallback(task_suite, fake_project) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    project = fake_project("projectRead")  # QGIS 3 name only
    warnings = plugin._wire_project_hooks(sess, project)
    assert warnings == []
    assert len(project.projectRead.slots) == 1


def test_project_hooks_reports_missing_read_signal(task_suite, fake_project) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    project = fake_project(None)  # no readProject/projectRead at all
    warnings = plugin._wire_project_hooks(sess, project)
    assert warnings and "project_read" in warnings[0]
    # layers/crs still got wired despite the missing read signal
    assert project.layersAdded.slots and project.crsChanged.slots


def test_canvas_hooks_log_extent_and_scale(task_suite, fake_canvas) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    canvas = fake_canvas()
    plugin._wire_canvas_hooks(sess, canvas)
    canvas.extentsChanged.fire()
    canvas.scaleChanged.fire(25000.0)
    record_path = sess.finish()
    events = [
        json.loads(line) for line in (sess.output_dir / "events.jsonl").read_text().splitlines()
    ]
    by_event = {entry["event"]: entry for entry in events}
    assert by_event["canvas_extent"]["extent"] == {
        "xmin": 0.0,
        "ymin": 1.0,
        "xmax": 100.0,
        "ymax": 51.0,
    }
    assert by_event["canvas_scale"]["scale"] == 25000.0
    assert record_path.exists()


def test_connect_host_hooks_project_and_canvas(
    monkeypatch, task_suite, fake_project, fake_canvas
) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    iface = types.SimpleNamespace(mapCanvas=lambda c=fake_canvas: c())
    _fake_qgis_modules(monkeypatch, project=fake_project("readProject"), iface=iface)
    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == ["project", "canvas"]
    assert failures == []


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


def test_connect_host_hooks_iface_absent(monkeypatch, task_suite, fake_project) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    _fake_qgis_modules(monkeypatch, project=fake_project("readProject"), iface=None)
    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == ["project"]
    assert failures == []


def test_connect_host_hooks_canvas_raises(monkeypatch, task_suite, fake_project) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    _fake_qgis_modules(
        monkeypatch,
        project=fake_project("readProject"),
        iface=None,
        iface_raises=AttributeError("iface blew up"),
    )
    connected, failures = plugin._connect_host_hooks(sess)
    assert connected == ["project"]
    assert failures and failures[0].startswith("canvas: ")


def test_start_message_lists_hooks_and_failures(task_suite) -> None:
    sess = session.start_session("demo-task-001", task_suite)
    message = plugin._start_message(sess, ["canvas"], ["project_read: missing"])
    assert "host hooks: canvas" in message
    assert "host hook failed: project_read: missing" in message
    assert session.sha256_file(sess.task_yaml) in message


# --- action surface (hello/start/log/end) ------------------------------------


def test_start_session_unknown_task_returns_error(task_suite) -> None:
    result = plugin.start_session(None, task_id="does-not-exist", base_dir=str(task_suite))
    assert result.startswith("cannot start session")


def test_second_start_is_refused_while_active(task_suite) -> None:
    first = plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    assert "session started" in first
    second = plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    assert second.startswith("session already active")
    message = plugin.end_session(None)
    assert "session ended" in message
    assert plugin._ACTIVE["session"] is None


def test_log_note_without_session_returns_message() -> None:
    assert plugin.log_note(None, "anything") == "no active session"


def test_log_note_records_and_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    (tmp_path / "t.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: f.geojson\n", encoding="utf-8"
    )
    (tmp_path / "f.geojson").write_text("{}", encoding="utf-8")
    plugin.start_session(None, task_id="demo-task-001", base_dir=str(tmp_path))
    reply = plugin.log_note(None, "re-read the prompt")
    assert "2 events so far" in reply
    plugin.end_session(None)


def test_end_session_without_active_session() -> None:
    assert plugin.end_session(None) == "no active session"


def test_end_session_writes_record_and_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    (tmp_path / "t.yaml").write_text(
        "id: demo-task-001\nfixtures:\n  input: f.geojson\n", encoding="utf-8"
    )
    (tmp_path / "f.geojson").write_text("{}", encoding="utf-8")
    plugin.start_session(
        None, task_id="demo-task-001", base_dir=str(tmp_path), participant_code="P-1"
    )
    message = plugin.end_session(None)
    assert "session ended" in message
    pattern = "session-*/human-reference-record.json"
    records = list((tmp_path / "baselines" / "demo-task-001").glob(pattern))
    assert len(records) == 1
    payload = json.loads(records[0].read_text())
    assert payload["participant_code"] == "P-1"
    assert plugin._ACTIVE["session"] is None


# --- session.py gaps ----------------------------------------------------------


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


# --- show_timer / SessionTimerDialog ----------------------------------------


def test_format_elapsed_pads_and_clamps() -> None:
    assert plugin._format_elapsed(0) == "00:00:00"
    assert plugin._format_elapsed(65) == "00:01:05"
    assert plugin._format_elapsed(3600 * 26 + 61) == "26:01:01"
    assert plugin._format_elapsed(-5) == "00:00:00"


def test_show_timer_without_active_session() -> None:
    assert plugin.show_timer(None) == "no active session — start one first"


def test_show_timer_opens_idle_panel_without_session() -> None:
    ui = _FakeUi()
    reply = plugin.show_timer(_FakeCtx(ui))
    assert reply.startswith("session panel opened")
    surface, initial = ui.calls[0]
    assert surface is plugin.SessionPanelDialog
    assert initial == {}


def test_show_timer_without_ui_capability(task_suite, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    reply = plugin.show_timer(None)  # pure tests: no ui capability
    assert "no ui capability" in reply
    plugin.end_session(None)


class _FakeUi:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def open(self, surface, *, initial=None):
        self.calls.append((surface, dict(initial or {})))


def test_show_timer_opens_dialog_with_initial(task_suite, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    ui = _FakeUi()
    reply = plugin.show_timer(_FakeCtx(ui))
    assert reply.startswith("session panel opened")
    surface, initial = ui.calls[0]
    assert surface is plugin.SessionPanelDialog
    assert initial["task_id"] == "demo-task-001"
    assert "T" in initial["started_at"]
    plugin.end_session(None)


def test_session_panel_dialog_registered() -> None:
    """The panel must be a registered surface or `ctx.ui.open` cannot reach it."""
    from qgis_sdk import describe_bindings

    surfaces = [s.surface.id for s in describe_bindings(plugin.app).surfaces]
    assert "session_panel_dialog" in surfaces


# --- SessionPanelDialog (fake Qt so the pure suite can run it) --------------


class _FakeSignal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def fire(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _FakeTimer:
    instances: list = []

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.interval = None
        self.started = False
        self.timeout = _FakeSignal()
        _FakeTimer.instances.append(self)

    def setInterval(self, ms) -> None:
        self.interval = ms

    def start(self) -> None:
        self.started = True


class _FakeWidget:
    def __init__(self) -> None:
        self.layout = None


class _FakeLabel:
    instances: list = []

    def __init__(self, text="") -> None:
        self._text = text
        self.style = None
        self.enabled = True
        _FakeLabel.instances.append(self)

    def setStyleSheet(self, style) -> None:
        self.style = style

    def setText(self, text) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _FakeLineEdit:
    def __init__(self, text="") -> None:
        self._text = text
        self.enabled = True
        self.object_name = ""

    def setObjectName(self, name) -> None:
        self.object_name = name

    def text(self) -> str:
        return self._text

    def setText(self, text) -> None:
        self._text = text

    def setEnabled(self, enabled) -> None:
        self.enabled = enabled


class _FakePushButton:
    def __init__(self, text="") -> None:
        self._text = text
        self.enabled = True
        self.clicked = _FakeSignal()
        self.object_name = ""

    def setObjectName(self, name) -> None:
        self.object_name = name

    def text(self) -> str:
        return self._text

    def setEnabled(self, enabled) -> None:
        self.enabled = enabled

    def setText(self, text) -> None:
        self._text = text

    def click(self) -> None:
        self.clicked.fire()


class _FakePlainTextEdit:
    def __init__(self) -> None:
        self._text = ""
        self.read_only = False
        self.object_name = ""

    def setObjectName(self, name) -> None:
        self.object_name = name

    def setReadOnly(self, read_only) -> None:
        self.read_only = read_only

    def setPlainText(self, text) -> None:
        self._text = text

    def toPlainText(self) -> str:
        return self._text


class _FakeLayout:
    instances: list = []

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.widgets: list = []
        self.layouts: list = []
        _FakeLayout.instances.append(self)
        if parent is not None:
            parent.layout = self

    def addWidget(self, widget) -> None:
        self.widgets.append(widget)

    def addLayout(self, layout) -> None:
        self.layouts.append(layout)


class _FakeTabWidget:
    def __init__(self) -> None:
        self.tabs: list = []
        self.object_name = ""

    def setObjectName(self, name) -> None:
        self.object_name = name

    def addTab(self, widget, title) -> None:
        self.tabs.append((title, widget))


class _FakeMessageBox:
    class StandardButton:
        Yes = 0x4000
        No = 0x10000

    _answer = StandardButton.Yes

    @classmethod
    def question(cls, parent, title, text, buttons, default):
        cls.last = (title, text)
        return cls._answer


class _FakeFileDialog:
    _next_path = ""

    @classmethod
    def getSaveFileName(cls, parent, caption, directory, filter_):
        return cls._next_path, filter_


def _install_fake_qt(monkeypatch) -> None:
    core = types.ModuleType("qgis.PyQt.QtCore")
    core.QTimer = _FakeTimer
    widgets = types.ModuleType("qgis.PyQt.QtWidgets")
    widgets.QWidget = _FakeWidget
    widgets.QLabel = _FakeLabel
    widgets.QVBoxLayout = _FakeLayout
    widgets.QHBoxLayout = _FakeLayout
    widgets.QLineEdit = _FakeLineEdit
    widgets.QPushButton = _FakePushButton
    widgets.QPlainTextEdit = _FakePlainTextEdit
    widgets.QTabWidget = _FakeTabWidget
    widgets.QMessageBox = _FakeMessageBox
    widgets.QFileDialog = _FakeFileDialog
    pyqt = types.ModuleType("qgis.PyQt")
    pyqt.QtCore = core
    pyqt.QtWidgets = widgets
    qgis_pkg = types.ModuleType("qgis")
    qgis_pkg.PyQt = pyqt
    monkeypatch.setitem(sys.modules, "qgis", qgis_pkg)
    monkeypatch.setitem(sys.modules, "qgis.PyQt", pyqt)
    monkeypatch.setitem(sys.modules, "qgis.PyQt.QtCore", core)
    monkeypatch.setitem(sys.modules, "qgis.PyQt.QtWidgets", widgets)
    _FakeTimer.instances = []
    _FakeLabel.instances = []
    _FakeLayout.instances = []
    _FakeMessageBox._answer = _FakeMessageBox.StandardButton.Yes
    _FakeFileDialog._next_path = ""


class _FakeActions:
    """Dispatch to the plugin's handlers like the view dispatcher does."""

    def __init__(self) -> None:
        self.calls: list = []

    def start_session(self, **kwargs):
        self.calls.append(("start_session", kwargs))
        return plugin.start_session(None, **kwargs)

    def end_session(self, **kwargs):
        self.calls.append(("end_session", kwargs))
        return plugin.end_session(None, **kwargs)

    def abandon_session(self, **kwargs):
        self.calls.append(("abandon_session", kwargs))
        return plugin.abandon_session(None, **kwargs)


class _FakeCtx:
    def __init__(self, ui=None, actions=None) -> None:
        self._ui = ui if ui is not None else _FakeUi()
        self._actions = actions if actions is not None else _FakeActions()

    def has(self, name) -> bool:
        return name in ("ui", "actions")

    @property
    def ui(self):
        return self._ui

    @property
    def actions(self):
        return self._actions


def _build_panel(monkeypatch, initial=None):
    _install_fake_qt(monkeypatch)
    dialog = plugin.SessionPanelDialog()
    dialog.initial = initial or {"task_id": "demo-task-001"}
    dialog.ctx = _FakeCtx()
    widget = dialog.build()
    return dialog, widget


def test_panel_tab_titles_and_buttons(monkeypatch) -> None:
    dialog, tabs = _build_panel(monkeypatch)
    assert [title for title, _ in tabs.tabs] == ["Timer", "Logs"]
    parts = dialog._parts
    assert [parts[k].text() for k in ("start_button", "stop_button", "restart_button")] == [
        "Start",
        "Stop",
        "Restart",
    ]
    assert parts["start_button"].enabled is True
    assert parts["stop_button"].enabled is False
    assert parts["restart_button"].enabled is False


def test_panel_start_stop_cycle(monkeypatch, task_suite) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["participant_edit"].setText("P-7")
    parts["start_button"].click()
    assert plugin._ACTIVE["session"] is not None
    assert parts["stop_button"].enabled is True
    assert parts["task_edit"].enabled is False
    assert "session started for task demo-task-001" in parts["status_label"].text()
    parts["stop_button"].click()
    assert plugin._ACTIVE["session"] is None
    assert plugin._LAST["session"] is not None
    record = plugin._LAST["session"]
    assert (record.output_dir / "human-reference-record.json").exists()
    assert parts["start_button"].enabled is True
    assert parts["stop_button"].enabled is False


def test_panel_restart_abandons_and_restarts(monkeypatch, task_suite, tmp_path) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["participant_edit"].setText("P-7")
    parts["start_button"].click()
    old_session = plugin._ACTIVE["session"]
    _FakeMessageBox._answer = _FakeMessageBox.StandardButton.Yes
    parts["restart_button"].click()
    new_session = plugin._ACTIVE["session"]
    assert new_session is not None and new_session is not old_session
    assert new_session.task_id == old_session.task_id
    assert new_session.participant_code == "P-7"
    # abandoned: marker written, no record
    assert (old_session.output_dir / "session-abandoned.json").exists()
    assert not (old_session.output_dir / "human-reference-record.json").exists()
    assert plugin._LAST["session"] is old_session


def test_panel_restart_cancelled_keeps_session(monkeypatch, task_suite) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["start_button"].click()
    session = plugin._ACTIVE["session"]
    _FakeMessageBox._answer = _FakeMessageBox.StandardButton.No
    parts["restart_button"].click()
    assert plugin._ACTIVE["session"] is session
    assert "cancelled" in parts["status_label"].text()


def test_panel_logs_tab_renders_active_session(monkeypatch, task_suite) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["start_button"].click()
    assert "session_start" in parts["log_edit"].toPlainText()
    assert "demo-task-001" in parts["log_header"].text()


def test_panel_export_writes_human_readable_log(monkeypatch, task_suite, tmp_path) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["start_button"].click()
    target = tmp_path / "exported-log.txt"
    _FakeFileDialog._next_path = str(target)
    parts["export_button"].click()
    content = target.read_text(encoding="utf-8")
    assert "human-baseline session log" in content
    assert "session_start" in content
    assert "export" not in content.splitlines()[0].lower()
    assert "exported" in parts["status_label"].text()


def test_panel_export_cancel_writes_nothing(monkeypatch, task_suite, tmp_path) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["start_button"].click()
    _FakeFileDialog._next_path = ""
    parts["export_button"].click()
    assert "cancelled" in parts["status_label"].text()


def test_panel_export_without_session_says_so(monkeypatch) -> None:
    dialog, _tabs = _build_panel(monkeypatch)
    parts = dialog._parts
    parts["export_button"].click()
    assert "no session to export" in parts["status_label"].text()


def test_panel_tick_frozen_on_stop(monkeypatch, task_suite) -> None:
    import re

    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["start_button"].click()
    tick_timer = _FakeTimer.instances[0]
    tick_timer.timeout.fire()
    parts["stop_button"].click()
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", parts["elapsed_label"].text())


def test_panel_actions_unavailable_degrades(monkeypatch, task_suite) -> None:
    class _NoActions(_FakeCtx):
        def has(self, name):
            return name != "actions"

        @property
        def actions(self):
            raise AssertionError("actions must not be read without the capability")

    _install_fake_qt(monkeypatch)
    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": "demo-task-001"}
    dialog.ctx = _NoActions()
    dialog.build()
    parts = dialog._parts
    parts["start_button"].click()
    assert "no actions capability" in parts["status_label"].text()


def test_panel_action_failure_is_reported(monkeypatch, task_suite) -> None:
    class _BrokenActions(_FakeActions):
        def start_session(self, **kwargs):
            raise RuntimeError("boom")

    _install_fake_qt(monkeypatch)
    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": "demo-task-001"}
    dialog.ctx = _FakeCtx(actions=_BrokenActions())
    dialog.build()
    parts = dialog._parts
    parts["start_button"].click()
    assert "start_session failed: boom" in parts["status_label"].text()


def test_apply_initial_and_tick_with_active_session(monkeypatch, task_suite) -> None:
    import re

    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    plugin.start_session(None, task_id="demo-task-001", base_dir=str(task_suite))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    assert "recording" in parts["status_label"].text()
    assert parts["task_edit"].text() == "demo-task-001"
    assert re.fullmatch(r"00:00:\d\d", parts["elapsed_label"].text())
    plugin.end_session(None)


def test_abandon_session_without_active_session() -> None:
    assert plugin.abandon_session(None) == "no active session"


def test_call_action_actions_unavailable(monkeypatch, task_suite) -> None:
    class _HasRaises(_FakeCtx):
        def has(self, name):
            raise RuntimeError("boom")

    _install_fake_qt(monkeypatch)
    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": "demo-task-001"}
    dialog.ctx = _HasRaises()
    dialog.build()
    dialog._parts["start_button"].click()
    assert "actions unavailable: boom" in dialog._parts["status_label"].text()


def test_call_action_unknown_action_name(monkeypatch, task_suite) -> None:
    _install_fake_qt(monkeypatch)
    dialog = plugin.SessionPanelDialog()
    dialog.initial = {"task_id": "demo-task-001"}
    dialog.ctx = _FakeCtx()
    dialog.build()
    assert dialog._call_action("no_such_action") == "unknown action no_such_action"


def test_panel_export_write_failure(monkeypatch, task_suite) -> None:
    monkeypatch.setattr(plugin, "_connect_host_hooks", lambda s: (["fake"], []))
    dialog, _tabs = _build_panel(monkeypatch, {"task_id": "demo-task-001"})
    parts = dialog._parts
    parts["task_edit"].setText("demo-task-001")
    parts["start_button"].click()
    _FakeFileDialog._next_path = "/no-such-directory-xyz/exported-log.txt"
    parts["export_button"].click()
    assert "export failed:" in parts["status_label"].text()
    plugin.end_session(None)
