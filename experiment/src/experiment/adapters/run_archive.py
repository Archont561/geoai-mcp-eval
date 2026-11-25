"""Single-zip persistence adapter for ExperimentRun with lazy submodel hydration."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from experiment.adapters._archive_artifacts import (
    build_artifact_refs,
    collect_dir_files,
    parse_transcript_entry,
    sha256_bytes,
)
from experiment.domain.run import (
    ArtifactKind,
    ArtifactRef,
    ExperimentRun,
    TranscriptEntry,
    TrialMeasurement,
    TrialRecord,
)

UTF8 = "utf-8"
RUN_INDEX_MEMBER = "run.json"
SUMMARY_MEMBER = "summary.md"
SCHEMA_MEMBER = "schema/experiment-run-v1.json"
TRIALS_PREFIX = "trials"
_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

__all__ = [
    "RUN_INDEX_MEMBER",
    "SCHEMA_MEMBER",
    "SUMMARY_MEMBER",
    "TRIALS_PREFIX",
    "UTF8",
    "ArchiveIntegrityError",
    "LazyTrialHandle",
    "RunArchive",
    "build_artifact_refs",
    "collect_dir_files",
]


class ArchiveIntegrityError(ValueError):
    """Raised when an archive member is missing or fails SHA-256 verification."""


def _trial_member_name(trial_id: str, rel_path: str) -> str:
    return f"{TRIALS_PREFIX}/{trial_id}/{rel_path}"


def _write_zip_bytes(archive: zipfile.ZipFile, member: str, data: bytes) -> None:
    info = zipfile.ZipInfo(filename=member, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


class LazyTrialHandle:
    """Lazy, memoized, SHA-256-verified reader for one trial's heavy zip members."""

    def __init__(
        self,
        archive: RunArchive,
        record: TrialRecord,
        measurement: TrialMeasurement | None,
    ) -> None:
        self._archive = archive
        self.record = record
        self.measurement = measurement
        self._refs: dict[str, ArtifactRef] = {ref.path: ref for ref in record.artifacts}
        self._bytes_cache: dict[str, bytes] = {}
        self._parsed_cache: dict[str, Any] = {}

    @property
    def loaded_members(self) -> frozenset[str]:
        """Relative artifact paths that have been decompressed and verified so far."""
        return frozenset(self._bytes_cache)

    def _find_by_kind(self, kind: ArtifactKind) -> ArtifactRef | None:
        for ref in self.record.artifacts:
            if ref.kind == kind:
                return ref
        return None

    def read_bytes(self, rel_path: str) -> bytes:
        """Read and SHA-256-verify a trial member on first access, then cache."""
        if rel_path in self._bytes_cache:
            return self._bytes_cache[rel_path]
        ref = self._refs.get(rel_path)
        if ref is None:
            raise ArchiveIntegrityError(
                f"trial {self.record.trial_id!r} declares no artifact {rel_path!r}"
            )
        data = self._archive.read_verified_member(self.record.trial_id, ref)
        self._bytes_cache[rel_path] = data
        return data

    def read_text(self, rel_path: str) -> str:
        return self.read_bytes(rel_path).decode(UTF8)

    def read_json(self, rel_path: str) -> Any:
        cache_key = f"json:{rel_path}"
        if cache_key not in self._parsed_cache:
            self._parsed_cache[cache_key] = json.loads(self.read_text(rel_path))
        return self._parsed_cache[cache_key]

    @property
    def transcript(self) -> list[TranscriptEntry]:
        """Lazily load and validate the trial's JSONL transcript entries."""
        if "transcript" not in self._parsed_cache:
            ref = self._find_by_kind("transcript")
            if ref is None:
                self._parsed_cache["transcript"] = []
            else:
                lines = [line for line in self.read_text(ref.path).splitlines() if line.strip()]
                self._parsed_cache["transcript"] = [
                    parse_transcript_entry(json.loads(line)) for line in lines
                ]
        return self._parsed_cache["transcript"]

    @property
    def deliverable(self) -> Any | None:
        """Lazily load the trial's primary JSON/GeoJSON deliverable if present."""
        ref = self._find_by_kind("deliverable")
        return self.read_json(ref.path) if ref is not None else None

    @property
    def oracle_passes(self) -> dict[str, Any] | None:
        """Lazily load the trial's multi-pass oracle determinism dump if present."""
        ref = self._find_by_kind("oracle_passes")
        return self.read_json(ref.path) if ref is not None else None


def _verify_and_write_trials(
    zout: zipfile.ZipFile,
    run: ExperimentRun,
    trial_files: Mapping[str, Mapping[str, bytes]],
) -> None:
    for trial_id in sorted(run.trials):
        trial = run.trials[trial_id]
        provided = trial_files.get(trial_id, {})
        for ref in trial.artifacts:
            if ref.path not in provided:
                raise ArchiveIntegrityError(
                    f"missing bytes for declared artifact {trial_id}/{ref.path}"
                )
            data = provided[ref.path]
            actual = sha256_bytes(data)
            if actual != ref.sha256:
                raise ArchiveIntegrityError(
                    f"SHA-256 mismatch while writing {trial_id}/{ref.path}: "
                    f"expected {ref.sha256}, got {actual}"
                )
            _write_zip_bytes(zout, _trial_member_name(trial_id, ref.path), data)


class RunArchive:
    """Single-zip handle exposing eager ExperimentRun metadata and lazy trial handles."""

    def __init__(self, path: Path, zip_file: zipfile.ZipFile, run: ExperimentRun) -> None:
        self.path = path
        self._zip = zip_file
        self.run = run
        self._handles: dict[str, LazyTrialHandle] = {}

    @classmethod
    def open(cls, path: Path) -> RunArchive:
        """Open a run zip and eagerly validate ``run.json`` without decompressing trials."""
        zf = zipfile.ZipFile(path, "r")
        try:
            raw_index = zf.read(RUN_INDEX_MEMBER)
            run = ExperimentRun.model_validate_json(raw_index)
        except Exception:
            zf.close()
            raise
        return cls(path, zf, run)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> RunArchive:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def read_verified_member(self, trial_id: str, ref: ArtifactRef) -> bytes:
        member = _trial_member_name(trial_id, ref.path)
        try:
            data = self._zip.read(member)
        except KeyError as exc:
            raise ArchiveIntegrityError(f"missing zip member {member!r}") from exc
        actual = sha256_bytes(data)
        if actual != ref.sha256:
            raise ArchiveIntegrityError(
                f"SHA-256 mismatch for {member!r}: expected {ref.sha256}, got {actual}"
            )
        return data

    def trial(self, trial_id: str) -> LazyTrialHandle:
        """Return a memoized lazy handle for ``trial_id``."""
        if trial_id not in self._handles:
            if trial_id not in self.run.trials:
                raise KeyError(f"unknown trial_id {trial_id!r} in archive {self.path}")
            self._handles[trial_id] = LazyTrialHandle(
                self,
                self.run.trials[trial_id],
                self.run.measurements.get(trial_id),
            )
        return self._handles[trial_id]

    def summary_markdown(self) -> str | None:
        try:
            return self._zip.read(SUMMARY_MEMBER).decode(UTF8)
        except KeyError:
            return None

    def schema_json(self) -> dict[str, Any] | None:
        try:
            return json.loads(self._zip.read(SCHEMA_MEMBER).decode(UTF8))
        except KeyError:
            return None

    def verify_all(self) -> None:
        """Verify SHA-256 checksums of every declared trial artifact in the archive."""
        for trial_id, trial in self.run.trials.items():
            for ref in trial.artifacts:
                self.read_verified_member(trial_id, ref)

    @classmethod
    def write(
        cls,
        path: Path,
        run: ExperimentRun,
        *,
        trial_files: Mapping[str, Mapping[str, bytes]] | None = None,
        summary_markdown: str | None = None,
    ) -> Path:
        """Write one self-contained, verified ``experiment-run-*.zip`` archive."""
        path.parent.mkdir(parents=True, exist_ok=True)
        index_bytes = (run.model_dump_json(indent=2) + "\n").encode(UTF8)
        schema_bytes = (
            json.dumps(ExperimentRun.model_json_schema(), indent=2, sort_keys=True) + "\n"
        ).encode(UTF8)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            _write_zip_bytes(zout, RUN_INDEX_MEMBER, index_bytes)
            _write_zip_bytes(zout, SCHEMA_MEMBER, schema_bytes)
            if summary_markdown is not None:
                _write_zip_bytes(zout, SUMMARY_MEMBER, summary_markdown.encode(UTF8))
            _verify_and_write_trials(zout, run, trial_files or {})
        return path

    @classmethod
    def merge_archives(
        cls,
        dest: Path,
        sources: Sequence[Path],
        *,
        expected_trials: Sequence[str] | None = None,
        summary_markdown: str | None = None,
    ) -> ExperimentRun:
        """Merge fragment archives into one canonical verified zip archive."""
        parts: list[ExperimentRun] = []
        collected_files: dict[str, dict[str, bytes]] = {}
        for source in sources:
            with cls.open(source) as archive:
                parts.append(archive.run)
                for trial_id, trial in archive.run.trials.items():
                    bucket = collected_files.setdefault(trial_id, {})
                    for ref in trial.artifacts:
                        bucket[ref.path] = archive.read_verified_member(trial_id, ref)
        merged = ExperimentRun.merge(parts)
        if expected_trials is not None:
            merged = merged.with_audit(expected_trials)
        cls.write(dest, merged, trial_files=collected_files, summary_markdown=summary_markdown)
        return merged
