"""Unit tests for ``experiment.cli._loader``."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from experiment.cli import app

REPO_ROOT = Path(__file__).resolve().parents[3]
runner = CliRunner()


def test_cli_app_registers_all_subcommands_and_tasknest_manifest() -> None:
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    for group in ("tasks", "run", "score", "env", "archive"):
        assert group in res.output

    from tasknest.discovery import discover_tasks
    from tasknest.validation import validate_registry

    tools_dir = REPO_ROOT / "tools"
    assert not list(tools_dir.glob("experiment_*.py"))
    assert not (tools_dir / "_experiment_common.py").exists()

    registry = discover_tasks(REPO_ROOT)
    validate_registry(registry)

    expected = {
        "experiment.preflight",
        "experiment.model",
        "experiment.run",
        "experiment.harvest",
        "experiment.summary",
        "experiment.prune-ci",
        "experiment.backend-check",
    }
    discovered = {
        name for name, task in registry.tasks.items() if task.package_name == "experiment"
    }
    assert expected.issubset(discovered)
    for name in expected:
        task = registry.tasks[name]
        assert task.is_manifest is True
        assert task.source_path == REPO_ROOT / "experiment" / "pyproject.toml"
