---
id: GEO-002
title: Build task-suite validator
status: Done
assignee: []
created_date: '2026-11-16T00:00:00Z'
updated_date: '2026-11-22T16:16:00Z'
labels: []
milestone: m-0
dependencies: []
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Implement the CI-enforced validator for the task-suite YAML before preregistration.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 All task files validate against the declared schema and have unique IDs.
- [x] #2 Every referenced oracle type is implemented and required licenses are present.
- [x] #3 The validator checks required trap coverage and has automated tests.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a JSON Schema v1 and a CLI validator for task YAML, unique IDs, provenance/licences, fixture paths, budgets, implemented oracle types, and required trap coverage.
2. Integrate validation into the experiment task runner and CI.
3. Add positive and negative automated tests.
<!-- SECTION:PLAN:END -->
