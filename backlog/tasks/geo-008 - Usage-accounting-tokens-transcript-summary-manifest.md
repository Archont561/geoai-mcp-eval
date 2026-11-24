---
id: GEO-008
title: Usage accounting (tokens in transcript/summary/manifest)
status: Done
assignee: []
created_date: '2026-11-22T00:00:00Z'
updated_date: '2026-11-24T15:45:00Z'
labels: []
milestone: m-0
dependencies:
  - GEO-003
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Record LLM usage per cell: input/output token counts (or explicit null + warning when the endpoint reports none) in transcript.jsonl, summed per run in summary.json and the manifest. Add `--max-cell-tokens` to cap runaway arms. Never estimate tokens client-side.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every cell transcript records usage or an explicit null with a warning when unavailable.
- [x] #2 summary.json carries per-run token sums; the manifest records run-level totals.
- [x] #3 `--max-cell-tokens` aborts a cell cleanly with a recorded reason; no silent truncation.
- [x] #4 Tests cover usage present, usage missing (null path), and cap exceeded.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Thread usage from `_chat_completions` responses into a per-cell usage accumulator.
2. Write per-cell and per-run aggregates; add the CLI cap flag with tests.
<!-- SECTION:PLAN:END -->
