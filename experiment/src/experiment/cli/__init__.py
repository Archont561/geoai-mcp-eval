"""Thesis experiment CLI — auto-discovers typer commands from cli/ modules."""

from __future__ import annotations

from experiment.cli._loader import app

__all__ = ["app"]
