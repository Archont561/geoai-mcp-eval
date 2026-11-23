# Plugin behaviour specifications

Gherkin specifications for the QGIS plugin. Each `.feature` file here is
executable: `experiment-qgis-plugin/tests/test_plugin_scenarios.py` binds every
scenario to a pytest test through pytest-bdd, and the steps load the whole
plugin through the real QGIS Desktop host factory
(`qgis_sdk.adapters.desktop.host`) so scenarios call the public action surface
and the real session panel.

| File | Covers |
| --- | --- |
| `hello.feature` | the action surface: greeting, declared actions, missing actions |
| `human-baseline.feature` | starting, noting, ending, and abandoning a session |
| `session-panel.feature` | the timer and logs panel, restart, log export |
| `host-observation.feature` | project and map-canvas hook wiring |

`tests/plugin_harness.py` holds the QGIS and Qt doubles and the fixtures; that
module isn't named `conftest.py` because pytest would then collide it with the
experiment suite's `conftest.py` in a whole-repository run.
