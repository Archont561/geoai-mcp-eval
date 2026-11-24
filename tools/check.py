"""Composite offline repository quality gate: alint + ruff + pytest + rumdl + architecture."""

from __future__ import annotations

from tasknest import tool


@tool(
    depends=["alint", "lint", "architecture", "test", "md"],
    description="Run the offline-friendly repository quality gate.",
)
def check() -> None:
    """Run the offline-friendly repository quality gate."""
