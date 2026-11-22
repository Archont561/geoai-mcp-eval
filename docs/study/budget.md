---
title: Budget and daily-limit arithmetic
short_title: Budget
description: >-
  Budget and daily-limit arithmetic from the frozen thesis specification: primary
  runs, stretch runs, human time, full-scale projection.
---

(fresh-budget)=

# Budget and daily-limit arithmetic

**Status:** pre-implementation design specification (post-professor-consultation).

---

- **Primary (needed):** 10 tasks × 5 arm-configs × 4 reps = **200 runs**; assume
  ≈ 8–12 tool interactions/run ⇒ ≈ 2 000 API round-trips; BigPickle daily limit
  accommodates ~day-scale; expect 2–4 calendar days with session-fresh pacing;
  token accounting treated as best-effort (RQ5).
- **Stretch:** A@N1/N2/N4 × 10 × 4 = 160 extra (+1–2 days). Only after primary
  is frozen-complete.
- **Human:** 10 tasks × ~20 min ≈ 3–4 h + recording overhead.
- **Full-scale (marked for post-pilot):** N ≥ 80 tasks × 5 × 4 ≈ 1 600 runs;
  paid pinned model; weeks.
