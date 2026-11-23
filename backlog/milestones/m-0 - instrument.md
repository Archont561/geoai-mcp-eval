---
id: m-0
title: "Instrument"
---

## Description

Harness completion milestone: the instrument must be correct, provenance-aware,
and honest before the pilot counts. Covers backends, usage accounting, caching,
the remote path, and the analysis data contract. Phase-gate milestone — gated on
evidence, not on dates.

Exit criteria:

- Backend profiles work end-to-end with the study pin (qwen2.5:3b) on a runner or workstation: both arms produce scored cells.
- Usage accounting lands: per-cell token usage (or explicit null + warning) in transcript.jsonl, sums in summary.json/manifest, and a `--max-cell-tokens` cap.
- Diskcache + `--no-cache` + `cache_hit` provenance in place; analysis does not read the cache (ADR recorded).
- Remote-Ollama preflight (`tools/experiment_backend_check.py`): ssh → tunnel → digest pin → one tiny completion → READY or loud fail.
- Analysis data prep emits the flat binary predicate matrix from real results.
- CI gate green: tasknest check (alint + ruff + pytest + rumdl).
