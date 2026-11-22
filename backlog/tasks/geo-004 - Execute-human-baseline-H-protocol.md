---
id: GEO-004
title: Execute human baseline H protocol
status: To Do
assignee: []
created_date: '2026-11-16T00:00:00Z'
updated_date: '2026-11-22T16:16:00Z'
labels: []
milestone: m-0
dependencies: []
documentation:
  - experiment/tasks/HUMAN-REFERENCE.md
  - experiment/tasks/human-reference-record.template.json
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Run the human reference protocol using the same oracle as agent runs. Capture the session and processing log; report H only after agent-run analysis is locked. H is a descriptive reference, not a baseline to beat.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The human reference uses the same frozen task and oracle contract as agent runs.
- [ ] #2 Session evidence and processing logs are retained with appropriate provenance and privacy controls.
- [ ] #3 The descriptive report is added only after agent-run analysis is locked.
<!-- AC:END -->
