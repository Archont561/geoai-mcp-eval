---
id: GEO-009
title: Diskcache results cache + CI actions/cache
status: Done
assignee: []
created_date: '2026-11-22T00:00:00Z'
labels: []
milestone: m-0
dependencies:
  - GEO-008
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cache LLM completions on disk keyed by sha256(backend_id | model digest | messages | tools schema | temperature | max_tokens). Successes only — never cache error payloads. Add `--no-cache`, `cache_hit` provenance per cell, opt-in CI restore for `.cache/llm` with restore-keys prefix accumulation, and an ADR: the cache is provenance, not an interchangeable result store; analysis must not depend on it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Cache keys include the model digest (not tag); error responses are never cached.
- [x] #2 `--no-cache` forces fresh completions; `cache_hit` is recorded per cell.
- [x] #3 CI workflow restores `.cache/llm` via actions/cache with a key prefix restore.
- [x] #4 ADR records the cache policy; analysis path contains no cache reads (enforced by test or review).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add diskcache layer in the backends module behind the profile; key from digest.
2. Surface cache_hit in summary/manifest and CI cache restore; write the ADR.
<!-- SECTION:PLAN:END -->
