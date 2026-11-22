"""Deterministic pilot oracle and three-pass repeatability gate."""

from __future__ import annotations

from ._base import AssertionResult as AssertionResult
from ._base import DeterminismReport as DeterminismReport
from ._base import OracleVerdict as OracleVerdict
from ._evaluators import _evaluate_assertion as _evaluate_assertion
from ._evaluators import evaluate_task as evaluate_task
from ._gate import run_determinism_gate as run_determinism_gate  # noqa: F401
from ._jenks import fisher_jenks_breaks as fisher_jenks_breaks  # noqa: F401

__all__ = [
    "AssertionResult",
    "DeterminismReport",
    "OracleVerdict",
    "evaluate_task",
    "fisher_jenks_breaks",
    "run_determinism_gate",
]
