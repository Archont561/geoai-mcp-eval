"""Re-export the plugin's shared fixtures and mock doubles for pytest.

The fixtures and QGIS/Qt doubles live in ``plugin_harness.py``. This file only
exists because pytest discovers fixtures through ``conftest.py``; keeping the
doubles out of it avoids the basename collision between this directory's
``conftest.py`` and ``experiment/tests/conftest.py`` when the whole repository
runs in one session.
"""

from __future__ import annotations

from plugin_harness import (  # noqa: F401
    active_session,
    copied_pilot_suite,
    fake_qgis_modules,
    loaded_plugin,
    panel,
    pilot_tasks,
    qt,
    raw_task_suite,
    recorded_take,
    recorded_take_without_processing,
    session_store,
    task_suite,
)

# `loaded_plugin` depends on `session_store`; both are imported above.
