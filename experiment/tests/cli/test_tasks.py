"""Unit tests for ``experiment.cli.tasks``."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from experiment.cli import app

runner = CliRunner()


def test_tasks_show_and_validate_json_output() -> None:
    show_res = runner.invoke(app, ["tasks", "show", "analysis-de9im-001", "--json"])
    assert show_res.exit_code == 0, show_res.output
    show_data = json.loads(show_res.stdout)
    assert show_data["id"] == "analysis-de9im-001"
    assert isinstance(show_data["assertions"], list)

    val_res = runner.invoke(app, ["tasks", "validate", "--json"])
    assert val_res.exit_code == 0, val_res.output
    val_data = json.loads(val_res.stdout)
    assert val_data["passed"] is True
    assert val_data["task_count"] >= 3
