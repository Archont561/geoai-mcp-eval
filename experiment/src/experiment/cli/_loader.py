"""Auto-discover typer apps from sibling cli/ modules.

Drop a new .py file (not starting with ``_``) into this directory that defines
a module-level ``app = typer.Typer(...)`` instance, and it will be mounted as a
sub-command automatically.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import typer

app = typer.Typer(help="Thesis experiment CLI: tasks, runs, scoring, archiving, and environments.")

_cli_dir = Path(__file__).resolve().parent

for _module_info in sorted(pkgutil.iter_modules([str(_cli_dir)]), key=lambda info: info.name):
    if _module_info.name.startswith("_"):
        continue
    _module = importlib.import_module(f"experiment.cli.{_module_info.name}")
    _candidate = getattr(_module, "app", None)
    if isinstance(_candidate, typer.Typer):
        app.add_typer(_candidate, name=_module_info.name)
