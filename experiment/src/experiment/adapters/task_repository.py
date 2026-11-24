"""Reading task files: path in, validated :class:`~experiment.domain.task.Task` out.

This is the only place that parses task YAML. Before it existed, five modules
read the same files and each decided differently what a valid task was --
``prototype.load_task`` accepted any mapping with an ``id``, ``analyze`` skipped
anything that was not a mapping, ``cli/pilot._find_task`` swallowed parse errors,
and the oracle re-parsed YAML it had already been handed. A task missing
``fixtures`` therefore loaded cleanly and failed later with a ``KeyError``
inside an agent cell.

Four failure modes, one exception type. They are kept distinct because the
callers need different behaviour: a directory scan skips unreadable files, while
a single named task must report why it could not be read.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from experiment.domain.task import Task

UTF8 = "utf-8"


class TaskLoadError(Exception):
    """A task file could not be read, parsed, or validated.

    ``path`` is carried so a caller can report *which* file failed without
    re-deriving it from the message.
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class TaskNotFoundError(LookupError):
    """No task in the suite carries the requested identifier."""

    def __init__(self, suite: Path, task_id: str) -> None:
        super().__init__(f"unknown task ID: {task_id} in {suite}")
        self.suite = suite
        self.task_id = task_id


def read_task_document(path: Path) -> dict[str, object]:
    """Read one task file into a plain mapping, without interpreting it.

    Separate from :func:`load_task` because the suite validator must report a
    *structurally invalid* task as a validation issue rather than an exception;
    it needs the mapping even when the mapping is wrong.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding=UTF8))
    except OSError as exc:
        raise TaskLoadError(path, f"cannot read: {exc.strerror or exc}") from exc
    except yaml.YAMLError as exc:
        raise TaskLoadError(path, f"cannot parse YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise TaskLoadError(path, "task document must be a YAML mapping")
    return raw


def load_task(path: Path) -> Task:
    """Read and validate one task file.

    Raises:
        TaskLoadError: the file is missing, unreadable, not YAML, not a mapping,
            or does not match the task schema.
    """
    document = read_task_document(path)
    try:
        return Task.model_validate(document)
    except ValidationError as exc:
        raise TaskLoadError(path, str(exc)) from exc


def discover_task_files(suite: Path) -> list[Path]:
    """Every task YAML in a suite directory, sorted.

    Only files are returned, and ``schema-v1.json`` is excluded by the glob --
    the schema lives beside the tasks but is not one.
    """
    return sorted(path for path in suite.glob("*.yaml") if path.is_file())


def load_suite(suite: Path) -> list[Task]:
    """Every task in a suite, in file order.

    Unreadable files raise: a caller that wants to tolerate them should scan
    with :func:`discover_task_files` and load individually.
    """
    return [load_task(path) for path in discover_task_files(suite)]


def find_task_file(suite: Path, task_id: str) -> Path:
    """The path of the task carrying ``task_id``.

    Raises:
        TaskNotFoundError: no task in the suite has that identifier.
    """
    for path in discover_task_files(suite):
        try:
            document = read_task_document(path)
        except TaskLoadError:
            continue  # an unparsable sibling must not hide a valid task
        if document.get("id") == task_id:
            return path
    raise TaskNotFoundError(suite, task_id)


def find_task(suite: Path, task_id: str) -> Task:
    """The validated task carrying ``task_id``."""
    return load_task(find_task_file(suite, task_id))


def discover_task_ids(suite: Path) -> tuple[str, ...]:
    """Sorted task IDs discovered from ``suite`` YAML definitions."""
    return tuple(sorted(task.id for task in load_suite(suite)))
