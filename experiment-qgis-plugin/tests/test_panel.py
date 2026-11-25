"""Unit tests for ``experiment_plugin.panel``."""

from __future__ import annotations

from experiment_plugin import panel


def test_format_elapsed_and_exception_detail() -> None:
    assert panel.format_elapsed(0) == "00:00:00"
    assert panel.format_elapsed(65) == "00:01:05"
    assert panel.format_elapsed(3600 * 26 + 61) == "26:01:01"
    assert panel.format_elapsed(-5) == "00:00:00"
    assert "boom" in panel.exception_detail(RuntimeError("boom"))
