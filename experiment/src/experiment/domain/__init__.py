"""Pure domain logic: algorithms and values that touch no files, no network.

Modules here are importable without a GIS stack, a framework, or a filesystem.
They are the leaves of the import graph: everything else may import them, they
import nothing from ``experiment`` outside this package.

The boundary is enforced by import-linter contracts in ``pyproject.toml``
(``pixi run tools run architecture``), not by convention.
"""

from __future__ import annotations

from experiment.domain.jenks import fisher_jenks_breaks as fisher_jenks_breaks  # noqa: F401

__all__ = ["fisher_jenks_breaks"]
