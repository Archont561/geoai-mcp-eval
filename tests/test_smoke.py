"""Smoke test: the experiment package imports and exposes a version."""

from __future__ import annotations

import experiment


def test_package_imports() -> None:
    assert experiment.__version__ == "0.1.0"
