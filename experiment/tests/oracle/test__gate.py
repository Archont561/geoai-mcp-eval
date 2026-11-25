"""Unit tests for ``experiment.oracle._gate``."""

from __future__ import annotations

from pathlib import Path

import yaml

from experiment.oracle import AssertionResult, OracleVerdict, run_determinism_gate

REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"
AXIS_TASK = "prep-axis-order-001"


def _task_path(task_id: str) -> Path:
    return TASK_ROOT / f"{task_id}.yaml"


def test_determinism_gate_rejects_inconsistent_and_missing_verdicts(tmp_path: Path) -> None:
    path = _task_path(AXIS_TASK)
    sequence = iter(
        [
            OracleVerdict(
                passed=True,
                checks=(AssertionResult(assertion_id="check", passed=True, message="pass"),),
            ),
            OracleVerdict(
                passed=False,
                checks=(AssertionResult(assertion_id="check", passed=False, message="fail"),),
            ),
            OracleVerdict(
                passed=True,
                checks=(AssertionResult(assertion_id="check", passed=True, message="pass"),),
            ),
        ]
    )
    inconsistent = run_determinism_gate(path, tmp_path, lambda *_: next(sequence))
    assert not inconsistent.passed
    assert not inconsistent.consistent

    missing_sequence = iter(
        [
            OracleVerdict(
                passed=True,
                checks=(AssertionResult(assertion_id="check", passed=True, message="pass"),),
            ),
            None,
            OracleVerdict(
                passed=True,
                checks=(AssertionResult(assertion_id="check", passed=True, message="pass"),),
            ),
        ]
    )
    missing = run_determinism_gate(path, tmp_path, lambda *_: next(missing_sequence))
    assert not missing.passed
    assert not missing.consistent
    assert any("missing" in issue for issue in missing.issues)


def test_determinism_gate_records_exception_and_rejects_bad_run_count(tmp_path: Path) -> None:
    def explode(*_args: object) -> OracleVerdict:
        raise RuntimeError("simulated oracle failure")

    report = run_determinism_gate(_task_path(AXIS_TASK), tmp_path, explode)
    assert not report.passed
    assert any("simulated oracle failure" in issue for issue in report.issues)

    task_yaml = _task_path(AXIS_TASK)
    task = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
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
