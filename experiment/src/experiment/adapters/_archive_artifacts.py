"""Artifact hashing, kind/media-type inference, and transcript parsing for run archives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from experiment.domain.run import ArtifactKind, ArtifactRef, TranscriptEntry

_TRANSCRIPT_KNOWN_FIELDS = frozenset(TranscriptEntry.model_fields) - {"extra_fields"}

_EXACT_KINDS: dict[str, ArtifactKind] = {
    "transcript.jsonl": "transcript",
    "result.json": "deliverable",
    "result.geojson": "deliverable",
}
_SUFFIX_KINDS: tuple[tuple[str, ArtifactKind], ...] = (
    (".gpkg", "deliverable"),
    (".log", "log"),
    (".py", "script"),
)
_SUFFIX_MEDIA_TYPES: tuple[tuple[str, str], ...] = (
    (".geojson", "application/geo+json"),
    (".json", "application/json"),
    (".jsonl", "application/x-ndjson"),
    (".log", "text/plain"),
    (".txt", "text/plain"),
    (".md", "text/plain"),
    (".py", "text/x-python"),
)


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def infer_artifact_kind(rel_path: str) -> ArtifactKind:
    """Classify a trial artifact path into an :data:`ArtifactKind`."""
    name = rel_path.rsplit("/", 1)[-1].lower()
    if name in _EXACT_KINDS:
        return _EXACT_KINDS[name]
    if name.startswith("oracle") and name.endswith(".json"):
        return "oracle_passes"
    for suffix, kind in _SUFFIX_KINDS:
        if name.endswith(suffix):
            return kind
    return "other"


def infer_media_type(rel_path: str) -> str | None:
    """Infer an HTTP media type from a trial artifact filename suffix."""
    lower = rel_path.lower()
    for suffix, media_type in _SUFFIX_MEDIA_TYPES:
        if lower.endswith(suffix):
            return media_type
    return None


def build_artifact_refs(
    files: Mapping[str, bytes],
    kinds: Mapping[str, ArtifactKind] | None = None,
) -> list[ArtifactRef]:
    """Build sorted ArtifactRef entries with exact SHA-256 hashes from raw bytes."""
    overrides = kinds or {}
    refs: list[ArtifactRef] = []
    for rel_path in sorted(files):
        data = files[rel_path]
        kind = overrides.get(rel_path) or infer_artifact_kind(rel_path)
        refs.append(
            ArtifactRef(
                path=rel_path,
                sha256=sha256_bytes(data),
                bytes=len(data),
                kind=kind,
                media_type=infer_media_type(rel_path),
            )
        )
    return refs


def collect_dir_files(root: Path) -> dict[str, bytes]:
    """Read every file under ``root`` into a sorted POSIX-relative bytes mapping."""
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            result[rel] = path.read_bytes()
    return result


def _normalize_content(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def parse_transcript_entry(raw: Mapping[str, Any]) -> TranscriptEntry:
    """Normalize a raw JSONL transcript dict into a :class:`TranscriptEntry`."""
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _TRANSCRIPT_KNOWN_FIELDS:
            known[key] = _normalize_content(value) if key == "content" else value
        else:
            extra[key] = value
    if "role" not in known:
        known["role"] = "unknown"
    return TranscriptEntry(**known, extra_fields=extra)
