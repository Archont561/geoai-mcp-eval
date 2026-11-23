---
title: Preregistration checklist
short_title: Preregistration
description: >-
  Preregistration checklist (what will live in Załącznik E) from the frozen thesis
  specification: document + YAML checksums, oracle details, run protocol, stopping
  rules, analysis scripts pinned.
---

(fresh-prereg)=

# Preregistration checklist

**Status:** pre-implementation design specification (post-professor-consultation).

---

## What will live in Załącznik E

- This document + YAML checksums; arm prompt scaffolds verbatim; catalogue JSON +
  hash; N-flag semantics (exact check order: syntax → enum/units → domain →
  postcondition).
- Oracle: assertion IDs, types, tolerances; third-party-checker versions;
  3× determinism evidence.
- Run protocol: randomisation list hash; session-freshness rule; logging schema
  (`results.jsonl` fields: `run_id, task_id, arm, N, stratum, seed?, model_id,
  date, driver, prompt_hash, artefact_path, artefact_sha256, tool_calls, repairs,
  assertions[], WSZ, OQS, wall_s, tokens?`); failure-class rubric with κ target.
- Stopping rules: oracle instability or log loss ≥ 1 % → stop, report instrument
  failure (not model failure).
- Analysis scripts pinned; alpha .05; correction family pre-named.

## Scope clarification (pre-freeze, 2026-11-22)

The confirmatory interface contrast is carried by the A and P families; the C
(Jenks) task is a pre-registered descriptive counter-case and never gates WSZ.
No visualization or cartographic-quality outcome enters pass/fail scoring; such
outcomes remain descriptive (F-family) only, by judgement and never by oracle.

## Addendum — arm B prompt scaffold tightened (pre-freeze, 2026-11-22)

Before Załącznik E freezes the scaffolds verbatim, the arm B system prompt was
corrected: it instructed the model to "Print the deliverable ... to stdout"
without requiring a ```python fenced block, while the harness executes only
```python fences — so a compliant model that answered with a ```json block (as
the task text suggests) was scored as failing, measuring instruction
contradiction rather than code-generation ability. The frozen text therefore
reads: "Reply with ONLY a single ```python fenced code block containing the
complete script; no prose and no other fences. The script must print the
deliverable ... to stdout". No other part of either scaffold changed; arm A was
left untouched. Verified pre-freeze with the local 0.5B coding model and (to be
recorded) the study pin on the runner.
