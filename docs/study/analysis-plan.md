---
title: Analysis plan — and its limits
short_title: Analysis plan
description: >-
  Analysis plan from the frozen thesis specification: determinism gate,
  completeness assertion, RQ1-RQ8 testing, multiple comparisons, scale path.
---

(fresh-analysis)=

# Analysis plan — and its limits

**Status:** pre-implementation design specification (post-professor-consultation).

---

## Steps

1. **Determinism gate** (blocking): oracle 3× identical on fixed artefacts; else
   stop — instrument invalid.
2. **Completeness assertion** (blocking): 200/200 runs logged; else stop (no
   silent imputation).
3. **RQ1 (gate):** exact McNemar on discordant task pairs (A pass/B fail vs A
   fail/B pass), two-sided; bootstrap 95 % CI on ΔWSZ (10 000 task resamples);
   Cliff’s δ. **Decision rule at pilot scale:** none — estimate only; a
   confirmatory verdict requires N ≥ 80 tasks (SEs/CIs recomputed;
   pre-registered analysis unchanged).
4. **RQ2:** ordinal contrast (linear) on WSZ across N-levels (A@N1..N4 if stretch
   runs exist; otherwise descriptive); plateau contrast N3→N4.
5. **RQ8:** silent-invalid rate per arm; exact Fisher; odds ratio + CI.
6. **RQ3:** stratified ΔWSZ with CIs per expressible stratum; flag as descriptive
   beyond pilot.
7. **RQ6, RQ4:** Hochberg within family; κ ≥ 0.6 gate for taxonomy use.
8. **RQ5/E/C/PH/I:** estimates + CIs; no p-claims.
9. **Multiple comparisons:** hierarchical gatekeeping (1→3→4→6/RQ6); family-wise
   α = .05; no peeks.
10. **Explicitly not done at this stage:** mixed-effects models (unstable at 10
    random tasks), power claims, MDE claims, rankings (“MCP better/worse”).
11. **Scale path:** with N ≥ 80 (× r = 4): swap descriptive tags → confirmatory
    (same machinery, powered); retain strata analyses; add sequential-monitoring
    audit if runs span weeks (provider drift).
