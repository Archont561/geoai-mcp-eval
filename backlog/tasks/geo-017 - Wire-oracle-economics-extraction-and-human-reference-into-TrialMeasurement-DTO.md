---
id: GEO-017
title: Wire oracle, economics extraction, and human reference into TrialMeasurement DTO
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - measurement
  - oracle
  - refactor
milestone: m-5
dependencies:
  - GEO-014
  - GEO-015
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Close the measurement gaps between the frozen study specification and the current code by computing complete, validated `TrialMeasurement` DTOs for every trial (both agent paradigms and the human reference protocol):

- Carry assertion `tier` (`trivial | spatial | value`) and `predicate` slug from `Task` YAML into every `AssertionResult`.
- Compute `task_success` (strict 0/1: 1 iff every oracle assertion passes), `predicate_score` (mean assertion pass fraction in `[0, 1]`), and `silent_invalid` (`True` iff deliverable passes trivial existence/readability checks yet fails a spatial or value assertion).
- Store typed `DeterminismAudit` (3-pass consistency, fingerprints, passed flag) instead of flattened `"pass"` / `"fail(exit=1)"` strings.
- Extract process/cost metrics from trial transcripts: `wall_seconds`, `llm_calls`, `tool_calls`, `repair_turns`, `schema_violations`, and nullable `TokenUsage` (never imputed).
- Add an adapter translating `experiment-qgis-plugin` human-reference records (`human-reference-record.template.json` v2) plus oracle verdicts into the exact same `TrialMeasurement` DTO (`paradigm="human_gui"`).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Scoring a trial produces a validated `TrialMeasurement` DTO with `task_success`, `predicate_score`, `silent_invalid`, assertion tiers/predicates, and extracted transcript metrics (`tool_calls`, `repair_turns`, `wall_seconds`, nullable `TokenUsage`).
- [ ] #2 The 3-pass oracle determinism gate populates a typed `DeterminismAudit` inside `TrialMeasurement` rather than an opaque status string.
- [ ] #3 `silent_invalid` accurately distinguishes missing/unreadable outputs from executable-but-invalid geospatial outputs (trivial pass + spatial/value fail).
- [ ] #4 Human reference records from `experiment-qgis-plugin` convert cleanly into `TrialMeasurement` DTOs with `paradigm="human_gui"` using the same oracle verdicts.
- [ ] #5 Unit tests cover all metric edge cases (partial token reporting, empty transcript, silent-invalid boundary, human-reference conversion).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Enrich `OracleVerdict` / `services/scoring.py` to propagate assertion `tier` and `predicate` from `Task` and construct `TrialMeasurement`.
2. Add pure transcript metric extractor in `domain/run/` for `tool_calls`, `repair_turns`, and `schema_violations`.
3. Update `oracle/_gate.py` and harvest scoring to emit typed `DeterminismAudit` objects.
4. Add human-reference record -> `TrialMeasurement` adapter and tests.
<!-- SECTION:PLAN:END -->
