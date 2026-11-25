"""Unit tests for ``experiment.cli.score``."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from experiment.cli import app

runner = CliRunner()


def test_score_eval_and_show_on_archive_and_directory(tmp_path: Path) -> None:
    out_dir = tmp_path / "mcp-score"
    res = runner.invoke(
        app,
        [
            "run",
            "mcp",
            "--task",
            "analysis-de9im-001",
            "--enforce",
            "N2",
            "--pack-zip",
            "--output-dir",
            str(out_dir),
        ],
    )
    assert res.exit_code == 0, res.output
    zip_path = out_dir.parent / f"experiment-run-{out_dir.name}.zip"

    eval_res = runner.invoke(app, ["score", "eval", str(zip_path)])
    assert eval_res.exit_code == 0, eval_res.output
    assert "analysis-de9im-001" in eval_res.output

    show_res = runner.invoke(app, ["score", "show", str(zip_path)])
    assert show_res.exit_code == 0, show_res.output
    assert "analysis-de9im-001" in show_res.output

    json_res = runner.invoke(app, ["score", "eval", str(out_dir), "--json"])
    assert json_res.exit_code == 0, json_res.output
    assert json.loads(json_res.stdout)["passed"] == 1
