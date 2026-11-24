"""Composite offline quality gate: alint, lint, clean_code, architecture, test, md."""

from __future__ import annotations

from tasknest import tool


@tool(
    depends=["alint", "lint", "clean_code", "architecture", "test", "md"],
    description="Run the offline-friendly repository quality gate.",
)
def check() -> None:
    """Run the offline-friendly repository quality gate."""
