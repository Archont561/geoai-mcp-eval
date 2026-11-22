---
id: GEO-001
title: Write 3 pilot task YAMLs (schema v1)
status: To Do
assignee: []
created_date: '2026-11-16T00:00:00Z'
labels: []
milestone: m-0
dependencies: []
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Define one prepare/IO, one analysis, and one cartography pilot task. Each task needs a stable ID, P/A/C family, human difficulty rubric, provenance and license, a human reference produced before agent runs, deterministic oracle checks, and a bounded run budget.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Three pilot task files cover prepare/IO, analysis, and cartography.
- [ ] #2 Each file validates against task-suite schema v1 and includes provenance, human-reference, oracle, and budget fields.
- [ ] #3 The pilot fixtures include the CRS/axis-order, topology/DE-9IM, and Jenks/classification traps.
<!-- AC:END -->
