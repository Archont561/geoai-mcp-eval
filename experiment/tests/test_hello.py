"""Tests for experiment.hello."""

from __future__ import annotations

from experiment.hello import hello_world


def test_hello_world() -> None:
    assert hello_world() == "Hello, world!"
