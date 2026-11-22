"""Lint Markdown and MDX prose with technical and scientific Vale styles."""

from __future__ import annotations

from tasknest import ToolContext, tool

PROSE_TARGETS = ["README.md", "AGENTS.md", "docs", "experiment/features"]


@tool(description="Lint Markdown and MDX prose with Vale style presets.")
def prose(ctx: ToolContext) -> None:
    """Install configured Vale packages, report every alert, then gate on errors."""
    ctx.run(["vale", "sync"])
    # Two passes over the same targets. The first is the advisory report: every warning
    # and error, with `--no-exit` so readability advice cannot fail the build. The second
    # is the gate: only `error`-level alerts are shown and Vale's own exit code stands, so
    # a broken term or a house-style breach fails CI while the review queue does not.
    ctx.run(["vale", "--no-exit", *PROSE_TARGETS])
    ctx.run(["vale", "--minAlertLevel=error", *PROSE_TARGETS])
