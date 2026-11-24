"""Task YAML discovery, hashing, and append-only behavior tracking."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment_plugin import _io


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_task_dir(base_dir: str | Path) -> Path:
    return Path(base_dir).expanduser().resolve()


def _search_task_dir(start: Path) -> Path | None:
    for parent in (start, *start.parents):
        candidate = parent / "experiment" / "tasks"
        if candidate.is_dir():
            return candidate.resolve()
    return None


def discover_task_dir(*, cwd: Path | None = None, anchor: Path | None = None) -> Path:
    """Locate experiment/tasks from cwd ancestors, then package ancestors."""
    current = (cwd or Path.cwd()).resolve()
    found = _search_task_dir(current)
    if found is not None:
        return found
    package_anchor = (anchor or Path(__file__)).resolve()
    search_start = package_anchor if package_anchor.is_dir() else package_anchor.parent
    found = _search_task_dir(search_start)
    if found is not None:
        return found
    return (current / "experiment" / "tasks").resolve()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    import yaml  # local import: pyyaml ships with the pixi env

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def find_task_yaml(base_dir: Path, task_id: str) -> Path:
    if not base_dir.is_dir():
        raise FileNotFoundError(
            f"task directory does not exist: {base_dir} (set EXPERIMENT_TASK_DIR or pass base_dir)"
        )
    parse_errors: list[str] = []
    for candidate in sorted(base_dir.glob("*.yaml")):
        try:
            data = _load_yaml_mapping(candidate)
        except Exception as exc:  # unreadable YAML: report, don't hide it
            parse_errors.append(f"{candidate.name}: {exc}")
            continue
        if data.get("id") == task_id:
            return candidate
    detail = f" (parse errors: {'; '.join(parse_errors)})" if parse_errors else ""
    raise FileNotFoundError(f"no task YAML with id={task_id!r} under {base_dir}{detail}")


def task_fixture(task_yaml: Path) -> Path:
    import yaml

    data = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
    return (task_yaml.parent / data["fixtures"]["input"]).resolve()


def baseline_dir_for(task_yaml: Path, task_id: str) -> Path:
    # experiment/tasks/baselines/<id> — matches .gitignore and HUMAN-REFERENCE.md
    return (task_yaml.parent / "baselines" / task_id).resolve()


@dataclass
class BehaviorTracker:
    """Append-only behavior event log written as JSONL."""

    events_path: Path
    started_at: datetime = field(default_factory=utc_now)
    event_count: int = 0

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": utc_now().isoformat(),
            "event": event,
            **{k: v for k, v in fields.items() if v is not None},
        }
        _io.append_jsonl(self.events_path, record)
        self.event_count += 1
        return record
