"""Compatibility imports for the former prototype cell runner.

New code should import execution from :mod:`experiment.services.runs` and
scoring from :mod:`experiment.services.scoring`. The original public names
remain available here for callers of the previous module.
"""

from experiment.adapters.task_repository import load_task as load_task
from experiment.harness import CellRequest as CellRequest
from experiment.harness import RunSpec as RunSpec
from experiment.services.runs import discover_tasks as discover_tasks
from experiment.services.runs import run_cell as run_cell
from experiment.services.runs import run_experiment as run_experiment
from experiment.services.scoring import score_cell as score_cell

__all__ = [
    "CellRequest",
    "RunSpec",
    "discover_tasks",
    "load_task",
    "score_cell",
    "run_cell",
    "run_experiment",
]
