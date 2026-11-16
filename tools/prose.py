"""Vale prose lint of the two standing Markdown docs (not part of `check`)."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Lint prose in README.md and AGENTS.md with vale.")
def prose(ctx: ToolContext) -> None:
    """Lint prose in README.md and AGENTS.md with vale."""
    ctx.run(["vale", "--no-exit", "README.md", "AGENTS.md"])
