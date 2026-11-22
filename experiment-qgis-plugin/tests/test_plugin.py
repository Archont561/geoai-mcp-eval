"""Smoke tests for Experiment Plugin — no QGIS install or display needed."""

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

    expected_ids = ["end_session", "hello", "log_note", "start_session"]
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
