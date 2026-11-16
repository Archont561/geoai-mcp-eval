"""Ruff check and format check of all Python sources."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Run ruff lint and ruff format --check.")
def lint(ctx: ToolContext) -> None:
    """Run ruff lint and ruff format --check."""
    ctx.run(["ruff", "check", "experiment", "tools"])
    ctx.run(["ruff", "format", "--check", "experiment", "tools"])
