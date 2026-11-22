"""Smoke tests for Experiment Plugin — no QGIS install or display needed."""

import pytest
from qgis_sdk import describe
from qgis_sdk.adapters.desktop import host

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

    assert [action.id for action in description.actions] == ["hello"]


def test_missing_action_raises_key_error() -> None:
    plugin = classFactory(None)
    plugin.initGui()
    try:
        with pytest.raises(KeyError):
            plugin.runtime.actions["missing"]()
    finally:
        plugin.unload()
