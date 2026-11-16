"""Auto-fix Python sources with ruff (lint --fix + format)."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Apply ruff autofixes and formatting (modifies files).")
def fmt(ctx: ToolContext) -> None:
    """Apply ruff autofixes and formatting (modifies files)."""
    ctx.run(["ruff", "check", "--fix", "experiment", "tools"])
    ctx.run(["ruff", "format", "experiment", "tools"])
