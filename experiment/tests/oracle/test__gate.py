"""Unit tests for ``experiment.oracle._gate``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from experiment.oracle import AssertionResult, OracleVerdict, run_determinism_gate

AXIS_TASK = "prep-axis-order-001"


def test_determinism_gate_rejects_inconsistent_and_missing_verdicts(
    tmp_path: Path, pilot_task_paths: dict[str, Path]
) -> None:
    path = pilot_task_paths[AXIS_TASK]
    pass_verdict = OracleVerdict(
        passed=True,
        checks=(AssertionResult(assertion_id="check", passed=True, message="pass"),),
    )
    fail_verdict = OracleVerdict(
        passed=False,
        checks=(AssertionResult(assertion_id="check", passed=False, message="fail"),),
    )

    inconsistent_eval = MagicMock(side_effect=[pass_verdict, fail_verdict, pass_verdict])
    inconsistent = run_determinism_gate(path, tmp_path, inconsistent_eval)
    assert not inconsistent.passed
    assert not inconsistent.consistent

    missing_eval = MagicMock(side_effect=[pass_verdict, None, pass_verdict])
    missing = run_determinism_gate(path, tmp_path, missing_eval)
    assert not missing.passed
    assert not missing.consistent
    assert any("missing" in issue for issue in missing.issues)


def test_determinism_gate_records_exception_and_rejects_bad_run_count(
    tmp_path: Path, pilot_task_paths: dict[str, Path]
) -> None:
    path = pilot_task_paths[AXIS_TASK]
    exploding_eval = MagicMock(side_effect=RuntimeError("simulated oracle failure"))
    report = run_determinism_gate(path, tmp_path, exploding_eval)
    assert not report.passed
    assert any("simulated oracle failure" in issue for issue in report.issues)

    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    task["oracle"]["determinism_runs"] = 2
    bad_task_path = tmp_path / "bad-runs.yaml"
    bad_task_path.write_text(yaml.safe_dump(task), encoding="utf-8")
    bad_report = run_determinism_gate(bad_task_path, tmp_path)
    assert not bad_report.passed
    assert any("exactly 3" in issue for issue in bad_report.issues)


def test_determinism_gate_reports_an_unloadable_task_instead_of_raising(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed\n", encoding="utf-8")

    report = run_determinism_gate(broken, tmp_path)

    assert not report.passed
    assert any(issue.startswith("task could not be loaded: ") for issue in report.issues)
