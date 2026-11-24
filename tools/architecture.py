"""Check the package import contracts declared in pyproject.toml."""

from __future__ import annotations

from tasknest import ToolContext, tool

# Both source roots are on PYTHONPATH for the check, so import-linter can resolve
# the packages it analyses the same way the test run does.
SOURCE_ROOTS = ["experiment/src", "experiment-qgis-plugin"]


@tool(
    marks=["lint"],
    description="Verify the layer boundaries with import-linter.",
)
def architecture(ctx: ToolContext) -> None:
    """Verify the layer boundaries with import-linter."""
    env = {"PYTHONPATH": ":".join(SOURCE_ROOTS)}
    ctx.run(["lint-imports", "--no-cache"], env=env)
