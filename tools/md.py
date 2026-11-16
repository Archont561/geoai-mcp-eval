"""Lint Markdown files with rumdl."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Lint Markdown files with rumdl.")
def md(ctx: ToolContext) -> None:
    """Lint Markdown files with rumdl."""
    ctx.run(["rumdl", "check", "."])
