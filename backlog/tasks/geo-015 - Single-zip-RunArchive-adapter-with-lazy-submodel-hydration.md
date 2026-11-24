---
id: GEO-015
title: Single-zip RunArchive adapter with lazy submodel hydration
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - refactor
  - adapters
milestone: m-5
dependencies:
  - GEO-014
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Implement a single centralized persistence adapter (`experiment/src/experiment/adapters/run_archive.py`) that saves and loads an entire `ExperimentRun` inside one self-contained `.zip` archive (`experiment-run-<run_id>.zip`), with lazy submodel hydration for heavy per-trial evidence.

Archive layout:

- `run.json`: validated `ExperimentRun` index (provenance, trial headers, all `TrialMeasurement` DTOs, `InstrumentAudit`).
- `summary.md`: human-readable Markdown digest matching `$GITHUB_STEP_SUMMARY`.
- `schema/experiment-run-v1.json`: exported `ExperimentRun.model_json_schema()`.
- `trials/<task_id>/<paradigm>/rep-<n>/`: raw immutable evidence (`transcript.jsonl`, `result.json` / `result.geojson`, `oracle-passes.json`, `ollama-serve.log`), each referenced by an `ArtifactRef` with SHA-256 checksum and byte size.

Eagerly reading `run.json` from the zip central directory keeps summary, scoring, and DataFrame queries fast even for 200+ trial runs, while lazy factory/loader accessors (`trial.transcript`, `trial.deliverable`, `trial.oracle_passes`) read, SHA-256 verify, and Pydantic-validate heavy members on first access and memoize them.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `RunArchive.write(path, run, ...)` writes a deterministic, self-contained `.zip` containing `run.json`, `summary.md`, `schema/experiment-run-v1.json`, and all trial evidence members with verified `ArtifactRef` SHA-256 hashes.
- [x] #2 `RunArchive.open(path)` eagerly validates `run.json` without decompressing trial transcripts, deliverables, or logs.
- [x] #3 Lazy submodel accessors hydrate and Pydantic-validate transcripts, deliverables, and oracle dumps on demand and fail loudly on SHA-256 mismatch or missing member.
- [x] #4 Fragment packing supports merging per-cell directories/fragment zips into one canonical `experiment-run-<run_id>.zip` via `ExperimentRun.merge(...)`.
- [x] #5 Unit tests verify round-trip fidelity, lazy non-loading before access, tamper detection on corrupted zip members, and Clean Code / `import-linter` compliance.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Design `RunArchive` and `LazyTrialHandle` in `experiment/src/experiment/adapters/run_archive.py` using stdlib `zipfile` and `hashlib`.
2. Add directory-to-archive migration/packing helpers so single-cell workers write clean fragments that `pack` combines into one `.zip`.
3. Retire ad-hoc `rglob()` discovery helpers in `run_store.py` once callers move to `RunArchive`.
4. Add unit tests covering eager index load, lazy hydration caching, and SHA-256 tamper rejection.
<!-- SECTION:PLAN:END -->
