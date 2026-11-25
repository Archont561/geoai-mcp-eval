"""Three-pass determinism gate for oracle evaluations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from experiment.adapters.task_repository import TaskLoadError
from experiment.adapters.task_repository import load_task as _load_task

from ._base import DeterminismReport, OracleVerdict
from ._evaluators import evaluate_task as _evaluate_task

RunFingerprint = tuple[bool, tuple[tuple[str, bool, str], ...]]
GatePass = tuple[dict[str, object], RunFingerprint | None, str | None]


# Kept as dataclass (not BaseModel): holds an opaque evaluator callable.
@dataclass(frozen=True)
class _GateContext:
    task_path: Path
    artifact_root: Path
    evaluator: Callable[[Path, Path], OracleVerdict | None]


def _gate_run_result(run_number: int, ctx: _GateContext) -> GatePass:
    try:
        verdict = ctx.evaluator(ctx.task_path, ctx.artifact_root)
    except Exception as exc:  # Keep later passes running after a recorded failure.
        message = f"{type(exc).__name__}: {exc}"
        result = {"run": run_number, "status": "error", "error": message}
        return result, None, f"run {run_number} errored: {message}"
    if verdict is None:
        message = "oracle produced no verdict"
        result = {"run": run_number, "status": "missing", "error": message}
        return result, None, f"run {run_number} is missing a verdict"
    result = {
        "run": run_number,
        "status": "passed" if verdict.passed else "failed",
        "verdict": verdict.to_dict(),
    }
    issue = None if verdict.passed else f"run {run_number} failed one or more oracle assertions"
    return result, verdict.fingerprint(), issue


def _gate_fingerprints_match(fingerprints: list[RunFingerprint | None], required_runs: int) -> bool:
    present = [fingerprint for fingerprint in fingerprints if fingerprint is not None]
    return len(present) == required_runs and len(set(present)) == 1


REQUIRED_DETERMINISM_RUNS = 3


def _gate_task_issue(task_path: Path) -> str | None:
    """Why this task cannot be gated, or None when it can.

    The task is loaded through the repository so the gate sees the same
    validated document the runner does. An unloadable task is a gate *issue*
    rather than an exception: the report is what a caller reads, and it should
    say why the gate could not run instead of raising past them.
    """
    try:
        task = _load_task(task_path)
    except TaskLoadError as exc:
        return f"task could not be loaded: {exc.reason}"
    required_runs = task.oracle.determinism_runs
    if required_runs != REQUIRED_DETERMINISM_RUNS:
        return (
            f"schema requires exactly {REQUIRED_DETERMINISM_RUNS} determinism runs; "
            f"found {required_runs!r}"
        )
    return None


def _collect_gate_results(
    ctx: _GateContext,
) -> tuple[list[dict[str, object]], list[RunFingerprint | None], list[str]]:
    results: list[dict[str, object]] = []
    fingerprints: list[RunFingerprint | None] = []
    issues: list[str] = []
    for run_number in range(1, 4):
        result, fingerprint, issue = _gate_run_result(run_number, ctx)
        results.append(result)
        fingerprints.append(fingerprint)
        if issue is not None:
            issues.append(issue)
    return results, fingerprints, issues


def run_determinism_gate(
    task_path: Path,
    artifact_root: Path,
    evaluator: Callable[[Path, Path], OracleVerdict | None] = _evaluate_task,
) -> DeterminismReport:
    """Run the oracle three times and fail on missing or inconsistent verdicts."""
    task_path = task_path.resolve()
    task_issue = _gate_task_issue(task_path)
    if task_issue is not None:
        return DeterminismReport(
            passed=False, required_runs=3, consistent=False, run_results=(), issues=(task_issue,)
        )
    ctx = _GateContext(task_path=task_path, artifact_root=artifact_root, evaluator=evaluator)
    results, fingerprints, issues = _collect_gate_results(ctx)
    consistent = _gate_fingerprints_match(fingerprints, 3)
    if not consistent:
        issues.append("oracle verdicts are missing or inconsistent across the three runs")
    passed = consistent and all(result.get("status") == "passed" for result in results)
    return DeterminismReport(
        passed=passed,
        required_runs=3,
        consistent=consistent,
        run_results=tuple(results),
        issues=tuple(issues),
    )
