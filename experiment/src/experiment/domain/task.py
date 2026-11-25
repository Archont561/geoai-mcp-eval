"""The task document: one validated pilot task, as a value.

Mirrors ``experiment/tasks/schema-v1.json`` field for field. Two rules keep the
two from drifting:

- ``extra="forbid"`` at every level, as the JSON Schema sets
  ``additionalProperties: false``. A field added to one without the other is a
  load error, not a silent difference.
- ``frozen=True``, because a task is a measuring instrument: the suite loader
  reads it, the runners read it, and nothing may rewrite it mid-run.

This module deliberately has no ``pathlib`` and no ``yaml``. Loading a file is
the repository's job (:mod:`experiment.adapters.task_repository`); this module
only knows the *shape* of a task and how to validate a mapping into it.

``assertions`` stays ``dict``-shaped on purpose. Oracle assertion types are
open-ended -- the schema validates the container, and the oracle dispatches on
``type`` -- so a closed union here would have to grow with every new assertion
type, in a layer that must not know about evaluators.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid", frozen=True)


class TaskFamily(StrEnum):
    """Pilot and study GIS task family code."""

    P = "P"
    A = "A"
    C = "C"

    def display_name(self) -> str:
        """Return the full English family name for reports and summaries."""
        labels: dict[TaskFamily, str] = {
            TaskFamily.P: "Prepare",
            TaskFamily.A: "Analyze",
            TaskFamily.C: "Cartography",
        }
        return labels[self]

    @classmethod
    def required_pilot_families(cls) -> frozenset[TaskFamily]:
        """Return the set of task families that a valid pilot suite must cover."""
        return frozenset(cls)


class Expressibility(StrEnum):
    """How expressible a task is through typed GIS tools."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Contamination(StrEnum):
    """Provenance contamination stratum of a task."""

    INHERITED = "inherited"
    CONSTRUCTED = "constructed"


class BaselineStatus(StrEnum):
    """Completion state of the task's human reference baseline."""

    PENDING = "pending"
    COMPLETE = "complete"


class DifficultyRubric(BaseModel):
    """How hard the task is for a human, in the units the study reports."""

    model_config = _STRICT

    tier: int = Field(ge=1, le=5)
    n_tools_human: int = Field(ge=0)
    n_steps_human: int = Field(ge=1)
    expressible: Expressibility


class Provenance(BaseModel):
    """Where the task came from, and whether it is inherited or constructed."""

    model_config = _STRICT

    source: str
    source_url: str
    source_file: str
    source_commit: str
    license: str
    contamination: Contamination


class Fixtures(BaseModel):
    """Input files, as paths relative to the task file's directory."""

    model_config = _STRICT

    input: str = Field(min_length=1)


class HumanBaseline(BaseModel):
    """The human reference record's state.

    Every field but ``status`` and ``artifact_dir`` is required *and* nullable:
    the schema models "not yet measured" as ``null`` rather than absence, so a
    pending baseline is still a complete record. Inventing defaults here would
    let a fabricated value pass for a measured one.
    """

    model_config = _STRICT

    status: BaselineStatus
    artifact_dir: str = Field(min_length=1)
    produced_with: str | None
    human_time_min: float | None = Field(default=None, ge=0)
    human_steps: int | None = Field(default=None, ge=0)
    human_tools: list[str]


class Oracle(BaseModel):
    """How the task is scored, and how many times the gate re-runs it."""

    model_config = _STRICT

    determinism_runs: int = Field(ge=1)
    assertions: list[dict[str, Any]]


class BudgetBounds(BaseModel):
    """Per-task ceilings on what an agent arm may consume."""

    model_config = _STRICT

    max_tool_calls: int = Field(ge=0)
    max_wall_s: int = Field(gt=0)


class Task(BaseModel):
    """One pilot task: the measuring instrument, validated."""

    model_config = _STRICT

    schema_version: int
    id: str = Field(min_length=1)
    title: str
    prompt: str
    family: TaskFamily
    difficulty_rubric: DifficultyRubric
    provenance: Provenance
    fixtures: Fixtures
    human_baseline: HumanBaseline
    oracle: Oracle
    budget_bounds: BudgetBounds
    runs: int = Field(ge=1)
    required_traps: list[str]

    @property
    def fixture_input(self) -> str:
        """The input fixture's path, relative to the task file."""
        return self.fixtures.input

    @property
    def assertion_ids(self) -> list[str]:
        """Named assertions, in document order, with unnamed ones marked."""
        return [str(assertion.get("id", "<unnamed>")) for assertion in self.oracle.assertions]
