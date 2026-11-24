"""Shared atomic text/JSON and JSONL helpers for the QGIS plugin package."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

UTF8 = "utf-8"
JSON_INDENT = 2


def format_json(payload: Any, *, trailing_newline: bool = False) -> str:
    """Render deterministic, key-sorted indented JSON."""
    text = json.dumps(payload, indent=JSON_INDENT, sort_keys=True)
    return text + "\n" if trailing_newline else text


def format_jsonl(records: Iterable[Mapping[str, Any]]) -> str:
    """Render key-sorted JSONL lines."""
    return "".join(json.dumps(dict(entry), sort_keys=True) + "\n" for entry in records)


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    """Append one key-sorted JSON object line to ``path``."""
    with path.open("a", encoding=UTF8) as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")


def write_atomic_text(
    target: Path,
    content: str,
    *,
    prefix: str,
    before_replace: Callable[[], None] | None = None,
) -> Path:
    """Stage ``content`` in a sibling temp file, run optional hook, and replace ``target``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(dir=target.parent, prefix=prefix, suffix=".tmp")
    tmp_path = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding=UTF8) as handle:
            handle.write(content)
        if before_replace is not None:
            before_replace()
        tmp_path.replace(target)
    except BaseException as error:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise BaseExceptionGroup(
                "record writing and cleanup failed", [error, cleanup_error]
            ) from None
        raise
    return target
