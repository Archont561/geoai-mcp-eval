"""Run pytest with coverage of the experiment package."""

from __future__ import annotations

import sys

from tasknest import ToolContext, tool


@tool(description="Run pytest with coverage of the experiment package.")
def test(ctx: ToolContext) -> None:
    """Run pytest with coverage of the experiment package."""
    env = {"PYTHONPATH": str(ctx.repo_root)}
    ctx.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=experiment",
            "--cov-report=term-missing",
            "--cov-report=xml:coverage.xml",
            "--cov-fail-under=90",
        ],
        env=env,
    )
