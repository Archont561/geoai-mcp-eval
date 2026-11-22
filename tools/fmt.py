"""Auto-fix Python sources with ruff (lint --fix + format)."""

from __future__ import annotations

from tasknest import ToolContext, tool

# Keep in step with `lint`: both run the same fixers over the same roots.
PYTHON_ROOTS = ["experiment", "experiment-qgis-plugin", "tools"]


@tool(description="Apply ruff autofixes and formatting (modifies files).")
def fmt(ctx: ToolContext) -> None:
    """Apply ruff autofixes and formatting (modifies files)."""
    ctx.run(["ruff", "check", "--fix", *PYTHON_ROOTS])
    ctx.run(["ruff", "format", *PYTHON_ROOTS])
