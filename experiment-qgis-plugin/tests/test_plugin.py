"""Smoke tests for Experiment Plugin — no QGIS install or display needed."""

import subprocess
import sys
from pathlib import Path

import pytest
from qgis_sdk import describe
from qgis_sdk.adapters.desktop import host

from experiment_plugin import session
from experiment_plugin.plugin import app

classFactory = host("experiment_plugin.plugin:app")


def test_the_plugin_starts_and_unloads_without_a_host() -> None:
    plugin = classFactory(None)
    plugin.initGui()
    try:
        assert plugin.runtime.state.value == "running"
        assert plugin.runtime.actions["hello"]("world") == "Hello, world!"
    finally:
        plugin.unload()
    assert plugin.runtime.state.value == "stopped"


def test_declared_actions_are_the_plugins_public_surface() -> None:
    description = describe(app)

    expected_ids = [
        "abandon_session",
        "end_session",
        "hello",
        "log_manual_action",
        "log_note",
        "show_timer",
        "start_session",
    ]
    assert [action.id for action in description.actions] == expected_ids


def test_missing_action_raises_key_error() -> None:
    plugin = classFactory(None)
    plugin.initGui()
    try:
        with pytest.raises(KeyError):
            plugin.runtime.actions["missing"]()
    finally:
        plugin.unload()


def test_version_is_single_sourced() -> None:
    """qgis-sdk build reads pyproject literally, so sync is pinned by test."""
    import tomllib

    import experiment_plugin

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert project["version"] == experiment_plugin.__version__
    assert experiment_plugin.__version__ == session.RECORDER_VERSION


def test_host_observation_import_has_no_native_or_plugin_dependency() -> None:
    """The extracted adapter must load without pulling in QGIS or the app."""
    script = """
import builtins
import sys

sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
native_imports = []

def watch_import(name, *args, **kwargs):
    if name.split('.')[0] in {'qgis', 'qgis_sdk'}:
        native_imports.append(name)
        raise ImportError(f'{name} is unavailable')
    return original_import(name, *args, **kwargs)

builtins.__import__ = watch_import
import experiment_plugin.host_observation
assert not native_imports, native_imports
assert 'experiment_plugin.plugin' not in sys.modules
"""
    plugin_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", script, str(plugin_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
