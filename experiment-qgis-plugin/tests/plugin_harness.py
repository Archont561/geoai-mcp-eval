"""Fixtures and host doubles for the plugin's behavioural scenarios.

This module is deliberately not named ``conftest.py``: pytest imports conftest
files under a bare basename, so two ``conftest.py`` modules in one run (here and
in ``experiment/tests``) collide and one shadows the other. The scenario module
imports from here directly and re-exports the fixtures pytest needs.


Every scenario drives the *whole plugin*: it is loaded through the real QGIS
Desktop host factory (``qgis_sdk.adapters.desktop.host``), so scenarios call the
public action surface (``runtime.actions``) and the real ``SessionPanelDialog``
exactly as QGIS would.

Two host details are supplied by this module rather than by QGIS:

* **Qt widgets.** The pure suite runs without a display, so a small Qt double is
  installed for the duration of a scenario (``install_fake_qt``). It implements
  only what the panel touches.
* **The desktop host.** ``qgis_sdk`` finds QGIS by importing ``qgis.core``. The
  ``install_host`` helper fakes that module so project and canvas hooks can be
  exercised, and leaves it absent by default (the standalone/no-QGIS host).

Nothing here re-implements plugin logic: the doubles stand in for QGIS and Qt,
never for ``experiment_plugin`` itself.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from qgis_sdk.adapters.desktop import host

from experiment_plugin import plugin, session

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"
UTF8 = "utf-8"

# Small, self-contained task suite for scenarios that must not depend on the
# shipped pilot tasks: one well-formed task, one unparseable manifest.
DEMO_TASK_ID = "demo-task-001"
DEMO_MANIFEST = (
    "id: demo-task-001\n"
    "title: Demo task\n"
    "fixtures:\n"
    "  input: fixture.geojson\n"
    "human_baseline:\n"
    "  status: pending\n"
    "  artifact_dir: baselines/demo-task-001\n"
)


# --- Qt doubles --------------------------------------------------------------


class FakeSignal:
    """A Qt signal: records slots and fires them on demand."""

    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def fire(self, *args) -> None:
        for slot in list(self.slots):
            slot(*args)

    def __call__(self, *args) -> None:
        self.fire(*args)


class FakeTimer:
    instances: list[FakeTimer] = []

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.interval = None
        self.started = False
        self.timeout = FakeSignal()
        FakeTimer.instances.append(self)

    def setInterval(self, ms) -> None:
        self.interval = ms

    def start(self) -> None:
        self.started = True


class FakeWidget:
    def __init__(self) -> None:
        self.layout = None


class FakeLabel:
    instances: list[FakeLabel] = []

    def __init__(self, text="") -> None:
        self._text = text
        self.style = None
        self.enabled = True
        FakeLabel.instances.append(self)

    def setStyleSheet(self, style) -> None:
        self.style = style

    def setText(self, text) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakeLineEdit:
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


class FakePushButton:
    def __init__(self, text="") -> None:
        self._text = text
        self.enabled = True
        self.clicked = FakeSignal()
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


class FakePlainTextEdit:
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


class FakeLayout:
    instances: list[FakeLayout] = []

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.widgets: list = []
        self.layouts: list = []
        FakeLayout.instances.append(self)
        if parent is not None:
            parent.layout = self

    def addWidget(self, widget) -> None:
        self.widgets.append(widget)

    def addLayout(self, layout) -> None:
        self.layouts.append(layout)


class FakeTabWidget:
    def __init__(self) -> None:
        self.tabs: list = []
        self.object_name = ""

    def setObjectName(self, name) -> None:
        self.object_name = name

    def addTab(self, widget, title) -> None:
        self.tabs.append((title, widget))


class FakeMessageBox:
    class StandardButton:
        Yes = 0x4000
        No = 0x10000

    _answer = StandardButton.Yes

    @classmethod
    def question(cls, parent, title, text, buttons, default):
        cls.last = (title, text)
        return cls._answer


class FakeFileDialog:
    _next_path = ""

    @classmethod
    def getSaveFileName(cls, parent, caption, directory, filter_):
        return cls._next_path, filter_


def install_fake_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the Qt double and reset its cross-scenario state."""
    core = types.ModuleType("qgis.PyQt.QtCore")
    core.QTimer = FakeTimer
    widgets = types.ModuleType("qgis.PyQt.QtWidgets")
    widgets.QWidget = FakeWidget
    widgets.QLabel = FakeLabel
    widgets.QVBoxLayout = FakeLayout
    widgets.QHBoxLayout = FakeLayout
    widgets.QLineEdit = FakeLineEdit
    widgets.QPushButton = FakePushButton
    widgets.QPlainTextEdit = FakePlainTextEdit
    widgets.QTabWidget = FakeTabWidget
    widgets.QMessageBox = FakeMessageBox
    widgets.QFileDialog = FakeFileDialog
    pyqt = types.ModuleType("qgis.PyQt")
    pyqt.QtCore = core
    pyqt.QtWidgets = widgets
    qgis_pkg = types.ModuleType("qgis")
    qgis_pkg.PyQt = pyqt
    monkeypatch.setitem(sys.modules, "qgis", qgis_pkg)
    # Cached native host modules are not children of the fake qgis package.
    # Isolate the panel doubles even when Pixi has already imported PyQGIS.
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    monkeypatch.setitem(sys.modules, "qgis.utils", None)
    monkeypatch.setitem(sys.modules, "qgis.PyQt", pyqt)
    monkeypatch.setitem(sys.modules, "qgis.PyQt.QtCore", core)
    monkeypatch.setitem(sys.modules, "qgis.PyQt.QtWidgets", widgets)
    FakeTimer.instances = []
    FakeLabel.instances = []
    FakeLayout.instances = []
    FakeMessageBox._answer = FakeMessageBox.StandardButton.Yes
    FakeFileDialog._next_path = ""


# --- QGIS host doubles -------------------------------------------------------


class FakeProject:
    """A QgsProject stand-in whose signals can be fired by a scenario."""

    def __init__(self, read_signal_name: str | None = "readProject") -> None:
        self.layersAdded = FakeSignal()
        self.layersWillBeRemoved = FakeSignal()
        self.crsChanged = FakeSignal()
        if read_signal_name:
            setattr(self, read_signal_name, FakeSignal())
        self.fileName = lambda: "/tmp/fake-project.qgs"

    @staticmethod
    def crs():
        class FakeCRS:
            @staticmethod
            def authid() -> str:
                return "EPSG:2180"

        return FakeCRS()


class FakeExtent:
    @staticmethod
    def xMinimum():
        return 0.0

    @staticmethod
    def yMinimum():
        return 1.0

    @staticmethod
    def xMaximum():
        return 100.0

    @staticmethod
    def yMaximum():
        return 51.0


class FakeCanvas:
    def __init__(self) -> None:
        self.extentsChanged = FakeSignal()
        self.scaleChanged = FakeSignal()

    @staticmethod
    def extent():
        return FakeExtent()


def install_host(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project: object | None = None,
    canvas: object | None = None,
    iface_raises: Exception | None = None,
) -> None:
    """Fake ``qgis.core``/``qgis.utils`` so the desktop host looks installed.

    With ``project`` left as ``None`` the module imports but ``QgsProject
    .instance()`` raises, which is the "standalone run, no project open" host.
    """
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
        utils.__getattr__ = lambda name: (_ for _ in ()).throw(iface_raises)
    else:
        canvas_factory: Callable[[], object] = canvas if canvas is not None else FakeCanvas
        utils.iface = types.SimpleNamespace(mapCanvas=canvas_factory)
    monkeypatch.setitem(sys.modules, "qgis.core", core)
    monkeypatch.setitem(sys.modules, "qgis.utils", utils)


def remove_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import qgis.core`` fail, i.e. no QGIS on this machine."""
    monkeypatch.setitem(sys.modules, "qgis.core", None)


# --- the plugin under test ---------------------------------------------------


class PluginHandle:
    """One loaded plugin, plus the UI surface the host would have opened."""

    def __init__(self) -> None:
        factory = host("experiment_plugin.plugin:app")
        self.plugin = factory(None)
        self.plugin.initGui()
        self.actions = self.plugin.runtime.actions
        self.opened: list[tuple[object, dict]] = []

    def call(self, action_id: str, **kwargs: Any) -> str:
        return self.actions[action_id](**kwargs)

    def open_surface(self, surface, *, initial=None) -> None:
        self.opened.append((surface, dict(initial or {})))

    def unload(self) -> None:
        self.plugin.unload()


class _ActionDispatcher:
    """Stand-in for the host's action dispatcher, as a view would see it.

    A view reaches the plugin's actions through the context. The real desktop
    context exposes no ``actions`` capability, so the scenarios hand the panel a
    dispatcher that forwards to the plugin's own action handlers — which is
    exactly what a GUI host does.
    """

    def __init__(self, handle: PluginHandle) -> None:
        self._handle = handle
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name: str):
        handler = self._handle.actions.get(name)
        if handler is None:
            raise AttributeError(name)

        def dispatch(**kwargs):
            self.calls.append((name, kwargs))
            return handler(**kwargs)

        return dispatch


def view_context(handle: PluginHandle, *, actions: Any = None) -> Any:
    """Return the host context a panel view is given.

    It reports the ``ui`` and ``actions`` capabilities, records surfaces opened
    through ``ui.open``, and dispatches actions to the plugin. Everything else
    delegates to the real runtime context.
    """
    dispatcher = actions if actions is not None else _ActionDispatcher(handle)

    class _ViewContext:
        def __init__(self, base) -> None:
            self._base = base

        def __getattr__(self, name):
            return getattr(self._base, name)

        def has(self, capability: str) -> bool:
            if capability in ("ui", "actions"):
                return True
            return self._base.has(capability)

        @property
        def ui(self):
            return types.SimpleNamespace(open=handle.open_surface)

        @property
        def actions(self):
            return dispatcher

    return _ViewContext(handle.plugin.runtime.context)


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def session_store():
    """Every scenario starts and ends with no active or last session."""
    plugin._ACTIVE["session"] = None
    plugin._LAST["session"] = None
    yield
    plugin._ACTIVE["session"] = None
    plugin._LAST["session"] = None


@pytest.fixture()
def task_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway task suite, also exported as $EXPERIMENT_TASK_DIR.

    The panel starts sessions through the ``start_session`` action, whose
    default base directory is that environment variable, so pointing it here is
    how a scenario makes panel-started sessions find the task.
    """
    (tmp_path / f"{DEMO_TASK_ID}.yaml").write_text(DEMO_MANIFEST, encoding=UTF8)
    (tmp_path / "fixture.geojson").write_text("{}", encoding=UTF8)
    (tmp_path / "broken.yaml").write_text("{not: [valid", encoding=UTF8)
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def pilot_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A writable copy of the shipped pilot suite (3 tasks + fixtures)."""
    import shutil

    root = tmp_path / "tasks"
    shutil.copytree(TASK_ROOT, root)
    monkeypatch.setenv("EXPERIMENT_TASK_DIR", str(root))
    return root


@pytest.fixture()
def raw_task_suite(tmp_path: Path) -> Path:
    """A throwaway task suite that does *not* set $EXPERIMENT_TASK_DIR."""
    (tmp_path / f"{DEMO_TASK_ID}.yaml").write_text(DEMO_MANIFEST, encoding=UTF8)
    (tmp_path / "fixture.geojson").write_text("{}", encoding=UTF8)
    return tmp_path


@pytest.fixture()
def qt(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qt(monkeypatch)


@pytest.fixture()
def loaded_plugin(session_store) -> PluginHandle:
    """The whole plugin, loaded and started through the desktop host factory."""
    handle = PluginHandle()
    try:
        yield handle
    finally:
        handle.unload()


@pytest.fixture()
def active_session(loaded_plugin: PluginHandle, task_suite: Path) -> dict[str, Any]:
    """A plugin with one running session, as a scenario would find it."""
    loaded_plugin.call("start_session", task_id=DEMO_TASK_ID, base_dir=str(task_suite))
    recorder = plugin._ACTIVE["session"]
    return {"handle": loaded_plugin, "recorder": recorder, "output_dir": recorder.output_dir}


@pytest.fixture()
def panel(qt: None, loaded_plugin: PluginHandle) -> Any:
    """Build a real ``SessionPanelDialog`` on the Qt double, idle."""

    def build(initial: dict[str, Any] | None = None):
        dialog = plugin.SessionPanelDialog()
        dialog.initial = initial or {}
        dialog.ctx = view_context(loaded_plugin)
        dialog.build()
        return dialog

    return build


def read_events(output_dir: Path) -> list[dict[str, Any]]:
    """Parse ``events.jsonl`` from a session directory."""
    path = output_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding=UTF8).splitlines() if line]


def read_record(output_dir: Path) -> dict[str, Any]:
    """Parse ``human-reference-record.json`` from a session directory."""
    return json.loads((output_dir / "human-reference-record.json").read_text(encoding=UTF8))


__all__ = [
    "DEMO_TASK_ID",
    "FakeCanvas",
    "FakeFileDialog",
    "FakeMessageBox",
    "FakeProject",
    "FakeTimer",
    "PluginHandle",
    "install_fake_qt",
    "install_host",
    "view_context",
    "read_events",
    "read_record",
    "remove_host",
    "session",
]
