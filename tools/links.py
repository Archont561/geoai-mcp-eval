"""Verify Markdown links offline with lychee."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Verify Markdown links offline with lychee.")
def links(ctx: ToolContext) -> None:
    """Verify Markdown links offline with lychee."""
    ctx.run(["lychee", "--offline", "README.md", "AGENTS.md"])
