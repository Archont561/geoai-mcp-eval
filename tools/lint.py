"""Run rude and Ruff checks across all Python sources."""

from __future__ import annotations

from tasknest import ToolContext, tool


@tool(description="Run rude, ruff lint, and ruff format --check.")
def lint(ctx: ToolContext) -> None:
    """Run rude, ruff lint, and ruff format --check."""
    ctx.run(
        [
            "python",
            "-m",
            "rude",
            "check",
            "experiment",
            "tools",
            "--config",
            "rude.toml",
            "--quiet",
        ]
    )
    ctx.run(["ruff", "check", "experiment", "tools"])
    ctx.run(["ruff", "format", "--check", "experiment", "tools"])
