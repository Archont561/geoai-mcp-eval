"""Run pytest with coverage of the experiment package."""

from __future__ import annotations

import os
import sys

from tasknest import ToolContext, tool


@tool(description="Run pytest with coverage of the experiment package.")
def test(ctx: ToolContext) -> None:
    """Run pytest with coverage of the experiment package."""
    source_paths = [
        ctx.repo_root / "experiment" / "src",
        ctx.repo_root / "experiment-qgis-plugin" / "src",
        ctx.repo_root,
    ]
    env = {"PYTHONPATH": os.pathsep.join(map(str, source_paths))}
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
