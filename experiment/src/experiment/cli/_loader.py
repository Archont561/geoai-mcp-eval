"""Auto-discover typer apps from sibling cli/ modules.

Drop a new .py file (not starting with ``__``) into this directory that defines
a ``typer.Typer`` instance, and it will be mounted as a sub-command
automatically. No model logic, no system prompt — just command files.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import typer

app = typer.Typer(help="Thesis experiment CLI.")

# Auto-discover and mount typer apps from sibling modules (skip __* files).
_cli_dir = Path(__file__).resolve().parent

for _module_info in pkgutil.iter_modules([str(_cli_dir)]):
    if _module_info.name.startswith("__"):
        continue
    if _module_info.name == "_loader":
        continue
    _module = importlib.import_module(f"experiment.cli.{_module_info.name}")
    for _attr_name in dir(_module):
        _attr = getattr(_module, _attr_name)
        if isinstance(_attr, typer.Typer):
            app.add_typer(_attr, name=_module_info.name)
