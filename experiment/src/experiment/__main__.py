"""Entry point for `python -m experiment`.

Imports the typer app from the cli subpackage and runs it.
"""

from __future__ import annotations

from experiment.cli._loader import app

if __name__ == "__main__":
    app()
