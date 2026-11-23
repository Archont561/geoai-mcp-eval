---
id: GEO-012
title: Flat binary predicate matrix on real results
status: To Do
assignee: []
created_date: '2026-11-22T00:00:00Z'
labels: []
milestone: m-0
dependencies: []
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Validate `experiment analyze flatten` against a complete scored results directory from the pilot (run_id, task, arm, driver, model + one 0/1 column per predicate). Confirm the predicate mapping (YAML `predicate:` keys) covers every assertion the pilot can emit, and document the semantics in the analysis notes (cells score 0 for predicates of other tasks; filter by task).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Flatten runs on the full pilot results dir and prints the expected matrix shape.
- [ ] #2 Every predicate column maps 1:1 to task-suite assertions (no missing mappings, no orphans).
- [ ] #3 Missing checks score 0; unknown assertions fail loudly.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Run the pilot, then `experiment analyze flatten` on the results root; diff column set vs task YAMLs.
2. Document semantics and known caveats in the analysis notes.
<!-- SECTION:PLAN:END -->
