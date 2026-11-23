"""Re-export the plugin's scenario fixtures so pytest can collect them.

The fixtures and QGIS/Qt doubles live in ``plugin_harness.py``. This file exists
only because pytest discovers fixtures through ``conftest.py``; keeping the
doubles out of it avoids the basename collision between this directory's
``conftest.py`` and ``experiment/tests/conftest.py`` when the whole repository
runs in one session.
"""

from __future__ import annotations

from plugin_harness import (  # noqa: F401
    active_session,
    loaded_plugin,
    panel,
    pilot_tasks,
    qt,
    raw_task_suite,
    session_store,
    task_suite,
)

# `loaded_plugin` depends on `session_store`; both are imported above.
