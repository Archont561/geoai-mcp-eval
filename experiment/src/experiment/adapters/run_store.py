"""Filesystem persistence for run, cell, and harvest artifacts.

Centralises JSON/JSONL reading and writing, SHA-256 artifact hashing, env-pin
serialization, and the canonical ``cell-<arm>-<task>-r<rep>/`` directory layout
so services stay free of ad-hoc filesystem I/O and dual-layout sniffing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

UTF8 = "utf-8"
JSON_INDENT = 2
CELL_DIR_PREFIX = "cell-"
_CELL_DIR_RE = re.compile(r"^cell-([A-Za-z]+)-(.+)-r([1-9]\d*)$")


class CellDir(BaseModel):
    """One discovered experiment cell directory under a run or harvest root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm: str
    task_id: str
    repetition: int = Field(ge=1)
    path: Path


def cell_dir_name(arm: str, task_id: str, repetition: int = 1) -> str:
    """Canonical directory name ``cell-<arm>-<task>-r<rep>`` for one cell."""
    if repetition < 1:
        raise ValueError(f"repetition must be >= 1, got {repetition}")
    return f"{CELL_DIR_PREFIX}{arm}-{task_id}-r{repetition}"


def cell_dir_path(root: Path, arm: str, task_id: str, repetition: int = 1) -> Path:
    """Canonical path ``<root>/cell-<arm>-<task>-r<rep>`` for one cell."""
    return root / cell_dir_name(arm, task_id, repetition)


def parse_cell_dir_name(name: str) -> tuple[str, str, int] | None:
    """Parse ``cell-<arm>-<task>-r<rep>`` into ``(arm, task_id, repetition)``."""
    match = _CELL_DIR_RE.match(name)
    if match is None:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing, then return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def exists(path: Path) -> bool:
    """Return True when ``path`` exists on disk."""
    return path.exists()


def is_file(path: Path) -> bool:
    """Return True when ``path`` refers to a regular file."""
    return path.is_file()


def is_dir(path: Path) -> bool:
    """Return True when ``path`` refers to an existing directory."""
    return path.is_dir()


def read_text(path: Path) -> str:
    """Read UTF-8 text from ``path``."""
    return path.read_text(encoding=UTF8)


def write_text(path: Path, content: str) -> Path:
    """Ensure parent exists and write UTF-8 text to ``path``."""
    ensure_dir(path.parent)
    path.write_text(content, encoding=UTF8)
    return path


def read_json(path: Path) -> Any:
    """Read and parse a JSON file from ``path``."""
    return json.loads(path.read_text(encoding=UTF8))


def read_json_mapping(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from ``path``, returning None when missing/invalid/non-dict."""
    try:
        data = json.loads(path.read_text(encoding=UTF8))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_json(
    path: Path,
    payload: Any,
    *,
    indent: int | None = JSON_INDENT,
    sort_keys: bool = True,
    trailing_newline: bool = False,
) -> Path:
    """Serialize ``payload`` as UTF-8 JSON to ``path``."""
    ensure_dir(path.parent)
    rendered = json.dumps(payload, indent=indent, sort_keys=sort_keys)
    if trailing_newline:
        rendered += "\n"
    path.write_text(rendered, encoding=UTF8)
    return path


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    """Append one compact, key-sorted JSON object line to ``path``."""
    ensure_dir(path.parent)
    line = json.dumps(dict(record), sort_keys=True, default=str) + "\n"
    with path.open("a", encoding=UTF8) as handle:
        handle.write(line)


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> Path:
    """Overwrite ``path`` with one key-sorted JSON line per record."""
    ensure_dir(path.parent)
    content = "".join(json.dumps(dict(r), sort_keys=True) + "\n" for r in records)
    path.write_text(content, encoding=UTF8)
    return path


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_hashes(cell_dir: Path) -> list[dict[str, object]]:
    """Inventory every file under ``cell_dir`` with relative path, sha256, and size."""
    files = sorted(path for path in cell_dir.rglob("*") if path.is_file())
    return [
        {
            "path": str(path.relative_to(cell_dir)),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in files
    ]


def find_first(root: Path, filename: str) -> Path | None:
    """Return the first sorted match for ``filename`` anywhere under ``root``."""
    matches = sorted(root.rglob(filename))
    return matches[0] if matches else None


def discover_manifests(harvest_dir: Path) -> list[Path]:
    """Every ``manifest.json`` file under ``harvest_dir``, sorted."""
    return sorted(harvest_dir.rglob("manifest.json"))


def discover_score_files(results_root: Path) -> list[Path]:
    """Every ``score.json`` file under ``results_root``, sorted."""
    return sorted(results_root.rglob("score.json"))


def _manifest_cell(path: Path) -> CellDir | None:
    record = read_json_mapping(path)
    if record is None:
        return None
    arm, task, rep = record.get("arm"), record.get("task"), record.get("rep")
    if type(arm) is not str or type(task) is not str:
        return None
    if type(rep) is not int or rep < 1:
        return None
    return CellDir(arm=arm, task_id=task, repetition=rep, path=path.parent)


def discover_cells(root: Path) -> list[CellDir]:
    """Discover all cells under ``root`` using canonical names or cell manifests."""
    found: dict[tuple[str, str, int], CellDir] = {}
    for manifest_path in discover_manifests(root):
        cell = _manifest_cell(manifest_path)
        if cell is not None:
            found.setdefault((cell.task_id, cell.arm, cell.repetition), cell)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            parsed = parse_cell_dir_name(child.name)
            if parsed is not None:
                arm, task_id, rep = parsed
                found.setdefault(
                    (task_id, arm, rep),
                    CellDir(arm=arm, task_id=task_id, repetition=rep, path=child),
                )
    return [found[key] for key in sorted(found)]


def find_cell_dir(harvest_dir: Path, arm: str, task: str, rep: int) -> Path | None:
    """Locate a cell directory inside ``harvest_dir`` (canonical or downloaded artifact)."""
    candidates = [
        cell_dir_path(harvest_dir, arm, task, rep),
        harvest_dir / f"experiment-{arm}-{task}-rep{rep}",
        *harvest_dir.glob(f"experiment-{arm}-{task}-rep{rep}*"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    for cell in discover_cells(harvest_dir):
        if (cell.arm, cell.task_id, cell.repetition) == (arm, task, rep):
            return cell.path
    return None


def read_env_pins(root: Path) -> dict[str, str]:
    """Parse ``key=value`` lines from the first ``env-pins.txt`` under ``root``."""
    path = find_first(root, "env-pins.txt")
    if path is None:
        return {}
    pins: dict[str, str] = {}
    for line in path.read_text(encoding=UTF8).splitlines():
        key, sep, value = line.partition("=")
        if sep:
            pins[key.strip()] = value.strip()
    return pins


def write_env_pins(path: Path, pins: Mapping[str, str]) -> Path:
    """Write ``key=value`` lines to ``path``."""
    return write_text(path, "".join(f"{key}={value}\n" for key, value in pins.items()))
