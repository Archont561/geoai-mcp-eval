"""Lint Markdown and MDX prose with technical and scientific Vale styles."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Lint Markdown and MDX prose with Vale style presets.")
def prose(ctx: ToolContext) -> None:
    """Install configured Vale packages and lint project prose."""
    ctx.run(["vale", "sync"])
    ctx.run(["vale", "--no-exit", "README.md", "AGENTS.md", "docs", "experiment/features"])
