---
id: GEO-003
title: Oracle determinism gate (3x identical verdicts)
status: Done
assignee: []
created_date: '2026-11-16T00:00:00Z'
updated_date: '2026-11-22T16:16:00Z'
labels: []
milestone: m-0
dependencies: []
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Implement a blocking determinism check: fixed artefacts must produce identical verdicts across independent oracle runs; missing runs must be surfaced, never imputed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The gate runs each fixed artefact through the oracle three independent times.
- [x] #2 Any inconsistent verdict or missing run fails the gate with an actionable report.
- [x] #3 Tests cover both passing and failing determinism cases.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Implement a deterministic oracle for the supported task assertion types.
2. Add a three-independent-run gate that rejects missing or inconsistent verdicts with actionable reports.
3. Add tests for stable verdicts, inconsistency, and missing runs.
<!-- SECTION:PLAN:END -->
