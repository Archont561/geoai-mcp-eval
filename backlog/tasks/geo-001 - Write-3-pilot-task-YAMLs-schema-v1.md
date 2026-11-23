---
id: GEO-001
title: Write 3 pilot task YAMLs (schema v1)
status: Done
assignee: []
created_date: '2026-11-16T00:00:00Z'
updated_date: '2026-11-22T16:16:00Z'
labels: []
milestone: m-1
dependencies: []
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Define one prepare/IO, one analysis, and one cartography pilot task. Each task needs a stable ID, P/A/C family, human difficulty rubric, provenance and license, a human reference produced before agent runs, deterministic oracle checks, and a bounded run budget.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Three pilot task files cover prepare/IO, analysis, and cartography.
- [x] #2 Each file validates against task-suite schema v1 and includes provenance, human-reference, oracle, and budget fields.
- [x] #3 The pilot fixtures include the CRS/axis-order, topology/DE-9IM, and Jenks/classification traps.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Use a pinned Natural Earth public-domain source and derive three compact fixtures.
2. Define and document the draft v1 task record, including provenance, traps, pending human references, oracle assertions, and budgets.
3. Validate all three YAML task files against the schema and required trap coverage.
<!-- SECTION:PLAN:END -->
