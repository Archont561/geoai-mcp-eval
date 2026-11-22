---
title: Experiment design — arms, materials, task suite, procedure
short_title: Experiment design
description: >-
  Factorial structure and arms (6.2), materials and environment (6.3), task
  suite YAML schema v1 (6.4), and procedure / freeze order (6.5).
---

(fresh-design)=

# Experiment design — arms, materials, task suite, procedure

**Status:** pre-implementation design specification (post-professor-consultation).

---

## 6.2 Factorial structure and arms

### Factors

Paradygmat (A vs B; C, D exploratory) · enforcement depth N1–N4 *within arm A*
(middleware flag, catalogue constant) · task family P/A/C (blocking) · expressible
share (moderator) · contamination stratum (inherited/constructed) · repetition
r = 4.

### Catalogue-constant rule (non-negotiable)

One server, one tool surface, one catalogue hash; depth is a single flag
(`--enforce=N1..N4`). If you cannot hold this constant, you measure catalog
design, not interface.

### Arms

| Arm | Configuration | Role in inference |
|---|---|---|
| **A** | Typed MCP only; N-flag middleware (primary execution at **N3**; full N-curve as stretch goal if budget permits) | Confirmatory (vs B) |
| **B** | CodeGen: Python free execution (PyQGIS/GeoPandas/…); checks only in post-hoc oracle (N0) | Confirmatory (vs A) |
| **C** | Typed MCP + one `execute_code` tool (mirrors deployed QGIS-MCP plugins) | Exploratory descriptor — bounds realism, not isolation; may collapse to B by construction |
| **D** | Agent generates Python that calls the typed MCP tools (client inside script) | Exploratory descriptor — “code as driver”; the practitioner pattern; N-flag still gates every call |
| **H** | Human analyst(s), GUI-first | Reference, not inference |

### Compute note

10 tasks × 5 configs × 4 reps = **200 runs** (A@N3).
Full ladder A(N1..N4) × 10 tasks × 4 reps adds 160 runs (stretch: +2 days within
daily limit; do A@N2/A@N4 only if the first day goes clean).

---

## 6.3 Materials and environment (explicit constraints)

- **Model:** OpenCode-hosted **BigPickle** (free tier; daily-request limit).
  Provider exposes no durable model pinning, seed, or guaranteed token accounting
  → mitigation: log `model_id`, `run_date`, `driver` hash, temperature on every
  record; treat provider drift as unmeasured variance bounded by r = 4; **do not**
  cite any result as “BigPickle shows…” beyond this scope.
- **Language/runtimes:** Python 3; `mcp` client; `geopandas`, `shapely`, `pyproj`,
  `rasterio`, `pyogrio`; QGIS LTR via dedicated profile; PROJ/GDAL versions pinned
  & recorded.
- **Engine:** QGIS LTR sandboxed from analysis; agent sees only tools (or none —
  B); no internet at run time except read-only fixture fetch pre-freeze.
- **Fixture discipline:** every input layer checksummed pre-freeze; artefacts +
  raw model output + tool log retained per run; no post-hoc tolerance changes.
- **Brief failure envelopes:** agent may produce nothing; count as WSZ = 0, never
  rerun “because it looked dumb”; zero silently dropped runs (Konkol/Nüst
  reproducibility ethics) [nust2018; konkol2019].

---

## 6.4 Task suite — YAML schema v1 (frozen)

```yaml
id: geop-prep-001                     # ^[a-z0-9][a-z0-9-]{2,40}$  — stable, never reused
title: "Buffer 500 m around schools; clip to district; dissolve; write layer"
prompt: |-                             # exact string shown to every arm (frozen)
  …
family: P                              # P=prepare/IO | A=analysis | C=cartography
difficulty:
  tier: 2                              # 1..5 derived from n_tools_human/n_steps_human (rubric in appendix)
  n_tools_human: 3
  n_steps_human: 5
  expressible: medium                  # low|medium|high — moderator for RQ3; cartography ≈ low by design
  est_steps: 5                         # human’s worked reference trajectory length
provenance:
  source: "GIS StackExchange <link> | author-constructed"
  license: "CC-BY-SA 4.0 | public domain | CC0"
  contamination: inherited              # inherited|constructed — strata analysed separately
baseline:
  artefact_dir: "tasks/geop-prep-001/baseline/"   # human-produced outputs (frozen before agent runs)
  produced_with: "QGIS 3.40 + Processing 'buffer', 2026-11-16"
  human_time_min: 18
  human_steps: 5
  human_tools: [native:buffer, native:clip, native:dissolve]
oracle:
  determinism_runs: 3                  # gate: identical verdicts ×3 on fixed artefacts pre-freeze
  assertions:
    - {id: exists,       tier: A, type: file_exists,     path: "out.gpkg"}
    - {id: readable,     tier: A, type: ogr_readable,    path: "out.gpkg"}
    - {id: crs,          tier: B, type: crs_equals,      path: "out.gpkg", expected: "EPSG:2180"}
    - {id: axis_order,   tier: B, type: axis_order_ok,   path: "out.gpkg"}
    - {id: geom_type,    tier: B, type: geom_type_in,    path: "out.gpkg", expected: [Polygon, MultiPolygon]}
    - {id: n_features,   tier: A, type: feature_count,   path: "out.gpkg", expected: 142, tol: 0}
    - {id: buffer_dist,  tier: C, type: min_dist_to,     path: "out.gpkg", tol_m: 1.0}
    - {id: valid_geom,   tier: B, type: geometry_valid,  path: "out.gpkg"}
    - {id: stats, tier: C, type: attr_stats, path: "out.gpkg", field: area_ha, mean_tol: 0.5}
budget: {max_tool_calls: 20, max_wall_s: 300}
runs: 4
notes: "known failure modes (NoData raster?) — informational only; never steers scoring"
```

### Validation rules (CI)

yamale/jsonschema check; unique `id`; every `oracle.type` implemented in the
checkers library; every `baseline.artefact_dir` present; contamination tag
present; licence string present; budget bounded; task human-verified to pass
oracle 100 % (sanity).

### Initial 10 tasks (proposal to freeze after pilot)

4 P, 4 A, 2 C; contamination ≈ 50/50 inherited/constructed; difficulty tiers 1–4;
at least one raster task, one topology/DE-9IM task, one CRS/axis-order trap, one
Jenks/classification task, one zonation/aggregation trap (MAUP), one NoData trap.
Licensing: GIS StackExchange inherits CC-BY-SA 4.0 — attribution in
`provenance.source`; author-constructed tasks are CC0.

---

## 6.5 Procedure (freeze order)

1. **Pilot** (3 tasks × {A@N3, B} × r=2): verify chain: fixture load → arm
   dispatch → artefact capture → oracle → log; tune only task bugs, never oracle
   thresholds post-hoc; measure wall-clock.
2. **Pre-freeze audit**: directory hash, fixture checksums, task-suite validator
   pass, oracle 3× determinism pass, human baseline H executed + oracle-verified,
   contamination tags spot-audited.
3. **Freeze** → tag `v1.0-prereg` (Załącznik E scope: this document + task
   checksums + seed table + protocol).
4. **Runs**: stratum-interleaved randomisation (P/A/C within stratum,
   inherited/constructed balanced); independent fresh session per run;
   wall-clock timestamps; auto-archive `results/<run_id>/`.
5. **Post-run, pre-analysis**: completeness assertion (200/200) — any missing run
   breaks analysis family, documented, not imputed silently.
