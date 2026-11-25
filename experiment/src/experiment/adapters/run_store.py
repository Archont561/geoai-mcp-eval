"""Filesystem persistence for run, cell, and harvest artifacts.

Centralises JSON/JSONL reading and writing, SHA-256 artifact hashing, env-pin
serialization, and run/harvest directory discovery so services stay free of
ad-hoc filesystem I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

UTF8 = "utf-8"
JSON_INDENT = 2


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


def discover_cell_dirs(run_dir: Path, arm_prefix: str) -> list[Path]:
    """Every ``<task>/<arm_prefix>*`` cell directory under ``run_dir``, sorted."""
    return [path for path in sorted(run_dir.glob(f"*/{arm_prefix}*")) if path.is_dir()]


def find_cell_dir(harvest_dir: Path, arm: str, task: str, rep: int) -> Path | None:
    """Locate an extracted cell directory inside ``harvest_dir``."""
    candidates = [
        harvest_dir / f"experiment-{arm}-{task}-rep{rep}",
        harvest_dir / task / arm / f"rep-{rep}",
        *harvest_dir.glob(f"experiment-{arm}-{task}-rep{rep}*"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
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
