---
title: Human reference protocol
short_title: Human reference
description: >-
  Human reference protocol (not an experimental arm) from the frozen thesis
  specification: QGIS profile, screen-capture, stopwatch, processing.log parsing,
  experimenter-bias control.
---

(fresh-human-ref)=

# Human reference protocol — not an experimental arm

**Status:** pre-implementation design specification (post-professor-consultation).

---

- Dedicated QGIS profile per human; screen-capture the whole session (audit for
  anything `processing.log` misses: styling, manual edits, dialog actions).
- Stopwatch: task prompt shown → artefact valid & saved to disk (oracle-verifiable)
  → stop. Record `human_time_min` to 0.5 min.
- After run: parse `processing.log` (profile `…/processing/processing.log`) for
  alg id + parameters + date/time → `human_trajectory.jsonl`; count calls →
  `human_steps`; manual/cognitive gaps labelled explicitly (never silently
  attributed to a tool).
- Human artefacts go through the **same oracle** → human WSZ. If humans silently
  corrupt (CRS!), that is a result, not a bug.
- Experimenter-bias control: tolerances frozen before *any* run (incl.
  human-first), human report appended only after agent-run analysis is locked;
  second coder audits ≥15 % of failure taxonomy.
- Fallback if GUI logging is insufficient: protocol + screen video suffices for a
  descriptive reference; no custom plugin needed at 10-task scale.
