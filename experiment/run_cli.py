"""Minimal CLI bootstrapper invoked by Tasknest manifest tasks in experiment/pyproject.toml."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
runpy.run_module("experiment", run_name="__main__")
