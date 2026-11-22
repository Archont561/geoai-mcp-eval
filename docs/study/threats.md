---
title: Threats to validity
short_title: Threats
description: >-
  Top 8 threats to validity with mitigations from the frozen thesis specification.
---

(fresh-threats)=

# Threats to validity

**Status:** pre-implementation design specification (post-professor-consultation).

---

| # | Threat | Mitigation |
|---|---|---|
| 1 | Model nondeterminism / provider drift | `model_id`+date logging; r=4; treat drift as variance; no external generalization claim |
| 2 | Task contamination (pretraining) | inherited/constructed strata; stratified reporting; constructed stratum sizes reported |
| 3 | Oracle ⊂ validator leak (testing own checks) | enumerate (enforced ∩ oracle) pre-freeze; prefer oracle-only predicates for RQ8 confirmatory claim |
| 4 | Catalogue-design confound | catalogue constant across N-levels; one hash; middleware flag only |
| 5 | Prompt scaffold asymmetry | byte-identical prompt except the interface block; scaffold frozen; both arms get identical tool *descriptions corpus* in B (as documentation) |
| 6 | Small-n overclaim | §6.8 gates; language bans “proves”; scaled study is the confirmatory stage |
| 7 | Human baseline bias (author-as-subject) | frozen tolerances; second coder; human results locked after agent analysis |
| 8 | Silent data loss / dropped runs | completeness assertion blocks analysis; zero-drop rule |
