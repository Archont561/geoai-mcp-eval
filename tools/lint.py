"""Run rude and Ruff checks across all Python sources."""

from __future__ import annotations

from tasknest import ToolContext, tool

# Both Python source roots, as declared in AGENTS.md and `[tool.pytest.ini_options]`.
# The plugin used to be skipped here, so its import order drifted until `ruff check`
# was run by hand against the whole repository.
PYTHON_ROOTS = ["experiment", "experiment-qgis-plugin", "tools"]


@tool(description="Run rude, ruff lint, and ruff format --check.")
def lint(ctx: ToolContext) -> None:
    """Run rude, ruff lint, and ruff format --check."""
    ctx.run(
        [
            "python",
            "-m",
            "rude",
            "check",
            *PYTHON_ROOTS,
            "--config",
            "rude.toml",
            "--quiet",
        ]
    )
    ctx.run(["ruff", "check", *PYTHON_ROOTS])
    ctx.run(["ruff", "format", "--check", *PYTHON_ROOTS])
