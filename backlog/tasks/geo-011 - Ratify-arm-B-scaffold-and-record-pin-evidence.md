---
id: GEO-011
title: Ratify arm-B scaffold and record study-pin evidence
status: To Do
assignee: []
created_date: '2026-11-22T00:00:00Z'
labels: []
milestone: m-0
dependencies:
  - GEO-009
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The arm-B system prompt was tightened pre-freeze (see preregistration addendum 2026-11-22): single ```python fenced block required. Record local 0.5B evidence and run the same arm-B cell against the study pin (qwen2.5:3b) on the CI runner or a workstation (1.9 GB sandbox RAM cannot host it). Fold the result into the preregistration addendum as the pre-freeze evidence; if the pin emits no python fence, record the finding — do not patch the prompt or harness post-hoc.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Local 0.5B smoke evidence is recorded in the preregistration addendum.
- [ ] #2 The pin (qwen2.5:3b) arm-B cell completes on a runner/workstation; score.json and transcript recorded.
- [ ] #3 The preregistration addendum carries the pin outcome verbatim; no prompt/harness change follows without a new addendum.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Ensure scaffold wording is frozen in the addendum; run the pin cell on hardware that fits it.
2. Record verdict, oracle result, and any deviation in the addendum.
<!-- SECTION:PLAN:END -->
