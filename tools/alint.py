"""Check repository policy via alint."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Check repository layout and policy with alint.")
def alint(ctx: ToolContext) -> None:
    """Check repository layout and policy with alint."""
    ctx.run(["alint", "check"])
