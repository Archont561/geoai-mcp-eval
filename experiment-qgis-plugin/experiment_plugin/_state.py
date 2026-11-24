"""Shared single-session runtime state for the Experiment Plugin."""

from __future__ import annotations

from typing import Any

from experiment_plugin import session as baseline

DEFAULT_TASK_ID = "prep-axis-order-001"
SESSION_KEY = "session"

# Single active session: one user on one desktop host at a time.
ACTIVE: dict[str, baseline.HumanBaselineSession | None] = {SESSION_KEY: None}

# Most recent terminal session (ended or abandoned), kept visible in Logs/Export.
LAST: dict[str, baseline.HumanBaselineSession | None] = {SESSION_KEY: None}

# Mutable holder for active session resources (avoids module-level `global` statements).
RUNTIME: dict[str, Any] = {"resources": None}
