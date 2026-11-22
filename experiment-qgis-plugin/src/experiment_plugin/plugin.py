"""Experiment Plugin: a minimal qgis-sdk plugin (hello world)."""

from __future__ import annotations

from qgis_sdk import QgisSdkPlugin
from qgis_sdk.core import PluginContext

app = QgisSdkPlugin(id="experiment_plugin", title="Experiment Plugin")


@app.action(id="hello", title="Hello")
def hello(_ctx: PluginContext, name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}!"
