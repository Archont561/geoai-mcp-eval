"""Validate lefthook.yml syntax and hook graph."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Validate lefthook.yml.")
def hooks_validate(ctx: ToolContext) -> None:
    """Validate lefthook.yml."""
    ctx.run(["lefthook", "validate"])
