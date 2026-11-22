---
id: GEO-003
title: Oracle determinism gate (3x identical verdicts)
status: To Do
assignee: []
created_date: '2026-11-16T00:00:00Z'
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
- [ ] #1 The gate runs each fixed artefact through the oracle three independent times.
- [ ] #2 Any inconsistent verdict or missing run fails the gate with an actionable report.
- [ ] #3 Tests cover both passing and failing determinism cases.
<!-- AC:END -->
