"""Re-export the experiment CLI scenario fixtures for pytest.

The fixtures and helpers live in ``cli_harness.py``. This file only exists so
pytest discovers them; keeping the content out of it avoids the basename
collision with ``experiment-qgis-plugin/tests/conftest.py`` in a whole-repository
run.
"""

from __future__ import annotations

from cli_harness import cli, results, suite  # noqa: F401
