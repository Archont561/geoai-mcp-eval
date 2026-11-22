"""Tests for experiment.cli.hello."""

from __future__ import annotations

from typer.testing import CliRunner

from experiment.cli.hello import app


def test_hello_command() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--name", "world"])
    assert result.exit_code == 0
    assert "Hello, world!" in result.output


def test_hello_command_default_name() -> None:
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Hello, world!" in result.output
