---
title: Measurements and scoring contract
short_title: Measurements and scoring
description: >-
  Measurements graded by asserting complexity (6.6) and formal scoring contract
  (6.7) for the frozen thesis specification.
---

(fresh-measurements)=

# Measurements and scoring contract

**Status:** pre-implementation design specification (post-professor-consultation).

---

## 6.6 Measurements, graded by asserting complexity

| Tier | Assert (what Python must do) | Examples | Cost to build |
|---|---|---|---|
| **A** trivial | exists/readable/count/format/size/schema/CRS tag | file_exists, ogr_readable, feature_count, raster_shape, nodata_ok, fields_present | minutes |
| **B** spatial predicates | shapely/GEOS/projection | crs_equals, axis_order_ok, geom_type_in, geometry_valid, de9im within/touches/covers, extent_within_tol, buffer_distance | half-day/task |
| **C** value-level vs baseline | tolerance comparisons | attr_stats, jenks_class_counts, IoU ≥ 0.5, centroid_offset, raster_cell_counts, hist_overlap | ~a day/task |
| **D** run-level repeatability/economics | logs/aggregates | WSZ, OQS, pass^4, ICC, tool-calls, wall-clock, repair turns, schema-violation rate, bypass/mixed-class rate | 1–2 days tooling |
| **E** comparative inference | stats | McNemar exact, bootstrap CIs, Cliff’s δ, ordinal contrast + plateau contrast, multinomial exact, Hochberg within family | analysis script |
| **F** semantic/judge | LLM/VLM | map legibility, ColorBrewer intent, label collisions — **descriptive only**, never decides WSZ; κ on double-coded subsample | optional |

---

## 6.7 Formal scoring contract

- `WSZ(run) = 1` iff every assertion in `oracle.assertions` passes. No partial
  credit inside WSZ.
- `OQS(run) = mean(assert_pass_i)` ∈ [0,1] — report mean and median per cell;
  beware skew (bimodal pass/fail).
- Aggregates per arm×task cell: WSZ̄, OQS, pass^4 (all r pass), ICC; per global:
  ΔWSZ(A,B) ∈ [−1,1], paired by task.
- Failure classes (coded from logs, double-coded on ≥15 %):
  `interface-adjacent` (tool pick/params), `workflow-silent` (CRS/units/aggregation),
  `hallucinated structure`, `other`.
- Trajectory classes (arms C/D): `typed-only`, `code-only`, `mixed` —
  collapse-rate = P(code-only) in arm C.
- Human reference: human_time_min (stopwatch), human_steps (Processing history
  units — one algorithm execution = 1 step, manual actions = count +1 each
  group), human tools list (parse `processing.log` date/time + params), human WSZ
  via the same oracle.
