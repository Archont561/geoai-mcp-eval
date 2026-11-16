"""Lint GitHub Actions workflows with actionlint."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Lint GitHub Actions workflows with actionlint.")
def actions(ctx: ToolContext) -> None:
    """Lint GitHub Actions workflows with actionlint."""
    ctx.run(["actionlint"])
