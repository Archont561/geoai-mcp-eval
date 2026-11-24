---
id: GEO-014
title: Unified English ontology domain models and TrialMeasurement DTO
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - refactor
  - domain
milestone: m-5
dependencies: []
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace the untyped dicts scattered across `manifest.json`, `score.json`, `summary.json`, and `env-pins.txt` with one strict Pydantic v2 aggregate root (`ExperimentRun`, `schema_version=1`, `extra="forbid"`) under `experiment/src/experiment/domain/run/`, using pure English ontology terms (no Polish acronyms in code or schemas).

Separating immutable execution records (`TrialRecord`) from derived measurements (`TrialMeasurement` DTO) lets oracle re-scoring and metric extraction evolve without mutating raw trial evidence, and gives agent paradigms and the human reference protocol one shared measurement contract.

Model hierarchy:

- `ExperimentRun`: `schema_version`, `run_id`, `stage`, `created_at`, `provenance`, `trials`, `measurements`, `instrument_audit`, plus pure `ExperimentRun.merge(parts)` for deterministic fan-out/fan-in combining.
- `EnvironmentPin` & `ModelPin`: pinned software versions (`repo_sha`, `pixi_lock_sha256`, `python`, `qgis`, `gdal`, `geos`, `proj`, `ollama`) and backend/model digest metadata.
- `Treatment`: `paradigm` (`typed_mcp | codegen | hybrid_mcp_code | code_driving_mcp | human_gui`), `enforcement_level` (`none | declarative | syntactic | semantic_repair | transactional`), `catalogue_hash`.
- `TrialRecord`: immutable header (`TrialKey`, execution `status`, `error`, `abort_reason`, cache hit/miss counts, `artifacts: list[ArtifactRef]`) referencing lazy heavy payloads (`transcript`, deliverables, logs).
- `TrialMeasurement` DTO: `assertions: list[AssertionResult]` (with `tier: trivial | spatial | value` and `predicate`), `determinism: DeterminismAudit | None`, `outcomes` (`task_success`, `predicate_score`, `silent_invalid`), `economics` (`wall_seconds`, `llm_calls`, `tool_calls`, `repair_turns`, `schema_violations`, nullable `TokenUsage`), and optional `annotations` (`trajectory_class`, `failure_class`, `semantic_judge`).
- `InstrumentAudit`: `expected_trials`, `logged_trials`, `missing_trials`, `extra_trials`, `complete`, `determinism_passed`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `experiment/src/experiment/domain/run/` defines `ExperimentRun`, `TrialRecord`, `TrialMeasurement`, `Treatment`, `EnvironmentPin`, `ModelPin`, and `InstrumentAudit` using Pydantic v2 (`extra="forbid"`, English names only).
- [ ] #2 `ExperimentRun.merge(parts)` deterministically combines partial runs from parallel jobs, rejects conflicting duplicate trials, and never imputes missing trials.
- [ ] #3 `ExperimentRun.model_json_schema()` exports cleanly as a self-describing JSON Schema.
- [ ] #4 `experiment.domain` remains 100% pure (zero I/O, `pathlib`, `zipfile`, or framework imports); all `import-linter` contracts and `clean_code` checks pass.
- [ ] #5 Unit and property tests verify strict validation, nullable token semantics (never coerced to 0), and merge invariants.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Create `experiment/src/experiment/domain/run/` split into cohesive submodules (`<=400` lines each, functions `<=30` lines) covering provenance, treatment/trial, measurement DTO, and aggregate root + merge.
2. Migrate `UsageSnapshot` / `TokenUsage` shapes in `domain/usage.py` to align with `TrialMeasurement.economics`.
3. Add unit tests for round-trip JSON serialization, `extra="forbid"` rejection, merge conflict handling, and JSON Schema export.
<!-- SECTION:PLAN:END -->
