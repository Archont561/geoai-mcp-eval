---
id: GEO-010
title: Remote-Ollama preflight (tools/experiment_backend_check.py)
status: Done
assignee: []
created_date: '2026-11-22T00:00:00Z'
labels: []
milestone: m-0
dependencies:
  - GEO-008
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Pre-flight check for the `remote-ollama` backend (SSH ControlMaster tunnel): verify the SSH tunnel, poll `/v1/models` until the expected digest appears, then issue one tiny completion and exit READY (with digest pin) or fail loudly with the cause (ssh unreachable, tunnel dead, model absent, completion rejected). Connection-issue and token-limit handling must be explicit — no retries that mask deterministic failures.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The tool exits READY with the pinned model digest only after a successful tiny completion.
- [x] #2 Missing/unreachable SSH host, dead tunnel, absent model, and token-limit responses each produce a distinct, actionable error.
- [x] #3 No silent retry on auth/4xx; retry only on 429/5xx per backend policy.
- [x] #4 Tests stub ssh/tunnel/HTTP paths.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Implement tunnel check (ControlMaster socket probe) + /v1/models digest poll with timeout.
2. One minimal completion; map failures to explicit exit codes and messages; tests with stubbed transport.
<!-- SECTION:PLAN:END -->
