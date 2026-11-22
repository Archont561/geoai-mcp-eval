---
id: GEO-002
title: Build task-suite validator
status: To Do
assignee: []
created_date: '2026-11-16T00:00:00Z'
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
- [ ] #1 All task files validate against the declared schema and have unique IDs.
- [ ] #2 Every referenced oracle type is implemented and required licenses are present.
- [ ] #3 The validator checks required trap coverage and has automated tests.
<!-- AC:END -->
