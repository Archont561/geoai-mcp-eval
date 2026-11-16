"""Install lefthook git hooks (pre-commit, pre-push)."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Install lefthook git hooks.")
def hooks(ctx: ToolContext) -> None:
    """Install lefthook git hooks."""
    ctx.run(["lefthook", "install"])
