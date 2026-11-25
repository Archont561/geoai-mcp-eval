"""Unit tests for ``experiment.services.scoring``."""

from __future__ import annotations

from pathlib import Path

from experiment.adapters import paths
from experiment.services import runs, scoring


def test_score_run_evaluates_and_reloads_run_summary(tmp_path: Path) -> None:
    out_dir = tmp_path / "run-score"
    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="A", task="analysis-de9im-001", backend="local")
    )
    runs.run_experiment(paths.tasks_root(), spec, out_dir)
    evaluated = scoring.rescore_run(out_dir, paths.tasks_root())
    assert evaluated.total == 1
    assert evaluated.passed == 1
    loaded = scoring.load_summary(out_dir)
    assert loaded.total == 1
    assert loaded.passed == 1
