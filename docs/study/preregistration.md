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
