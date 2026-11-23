---
title: Experiment setup
short_title: Experiment
description: >-
  Arms A/B/C/D/H, catalogue-constant rule, task-suite v1 proposal, freeze order,
  and scoring—the operational design behind the research questions.
---

(experiment)=

:::{warning} Pre-experiment—not frozen
The protocol is open until freeze. Everything on this page is a rendering of the frozen
specification (post-consultation); the specification wins on any disagreement. Arms C, D
are exploratory descriptors, not inferential factors.
:::

## Arms and factors

| Arm | Configuration | Role in inference |
|---|---|---|
| **A** | Typed MCP only; N-flag middleware (primary execution at N3; full N-curve only if budget permits) | **Confirmatory (vs B)** |
| **B** | CodeGen: Python free execution (PyQGIS/GeoPandas/…); post-hoc oracle checks only (N0) | **Confirmatory (vs A)** |
| **C** | Typed MCP + one `execute_code` tool (mirrors deployed QGIS-MCP plugins) | Exploratory descriptor—bounds realism; may collapse to B by construction |
| **D** | Agent generates Python that calls the typed MCP tools (client inside script) | Exploratory descriptor—practitioner pattern; N-flag still gates every call |
| **H** | Human analysts, GUI-first | Reference, not inference |

**Factors.** Paradigm (A vs B; C, D exploratory) · enforcement depth N1–N4 within arm A
(middleware flag; catalogue constant) · task family P/A/C (blocking) · expressible share
(moderator) · contamination stratum (inherited/constructed) · repetition r = 4.

:::{important} Catalogue-constant rule (non-negotiable)
One server, one tool surface, one catalogue hash; depth is a single flag
(`--enforce=N1..N4`). If this cannot be held constant, the experiment measures
catalogue design, not the interface.
:::

## Task suite (v1, to freeze after pilot)

- **Proposed initial suite:** 10 tasks—4 P (prepare/IO), 4 A (analysis), 2 C (cartography);
  contamination ≈ 50/50 inherited/constructed; difficulty tiers 1–4.
- **Mandatory traps:** at least one raster task, one topology/DE-9IM task, one
  CRS/axis-order trap, one Jenks/classification task, one zonation/aggregation trap
  (MAUP), one NoData trap [@openshaw1984maup; @iso19157].
- **YAML schema v1** (frozen at freeze): stable `id`, P/A/C family, difficulty rubric
  (n_tools_human, n_steps_human), provenance (source, licence, contamination tag),
  human baseline produced before agent runs, oracle (≥3 determinism runs, tiered
  assertions), budget bounds. Validation: schema check, unique ids, every oracle type
  implemented, licence strings present—all CI-enforced pre-freeze.
- **Licensing:** inherited GIS StackExchange tasks are CC BY-SA 4.0 (attribution mandatory);
  author-constructed tasks are CC0—see [Provenance](../provenance.md).

## Demand anchor (GIS Stack Exchange; supplied counts, retrieval date unverified)

The full analysis (method, all 29 counts, 27-row complexity ranking, catalogue gaps) is on the [SE demand analysis](../analysis.md) page; the anchor table:

| Operation | SE tag count | Operation | SE tag count |
|---|---:|---|---:|
| buffer | 1 533 | spatial join | 1 014 |
| clip | 1 391 | zonal statistics | 572 |
| merge | 1 284 | dissolve | 547 |
| raster calculator | 1 296 | overlay | 512 |
| field calculator | 2 562 | jenks | 9 |

Jenks at 9 is a counter-case by design—it tests the pre-registered cartography
hypothesis on the literature, not on SE volume. Counts measure demand, not difficulty
[@mastouri2025automcp]; they select tasks, they validate nothing—the oracle decides
correctness. Known catalogue gaps to close before freeze (legitimate instrument changes):
field calculator; merge; ideally point_distance.

## Freeze order

1. **Pilot**—3 tasks × {A@N3, B} × r=2; verify the whole chain (fixture → dispatch →
   artefact → oracle → log); tune task bugs only, never oracle thresholds post-hoc.
2. **Pre-freeze audit**—directory hash, fixture checksums, task-suite validator,
   oracle 3× determinism, human baseline H executed + oracle-verified, contamination
   spot-audit.
3. **Freeze**—tag `v1.0-prereg` (specification + task checksums + seed table).
4. **Runs**—stratum-interleaved randomisation; fresh session per run; the run directory archived automatically.
5. **Completeness assertion**—N≥80×4 runs logged; any missing run breaks the analysis
   family, documented, never silently imputed.

## Scoring and analysis (by reference)

Scored on executed artefacts via ISO 19157-derived predicates (tiers A–D: existence →
spatial predicates → value-level vs baseline → repeatability/economics). The formal
scoring contract (WSZ/OQS definitions, weights, tie handling) and the full analysis plan
with its limits are defined in the specification §§6.7–6.8 and are intentionally **not**
restated here. Preregistration → **Appendix E** (outside this repository).

## Threats and the human reference

Top threats (model pinning, provider drift, ceiling effects, catalogue confounds,
oracle bugs, prompt sensitivity, leakage, judging validity) and the human-reference
protocol (same oracle, screen-capture, processing.log parsing, report appended only
after agent-run analysis is locked) are specified in the frozen specification §§6.6,
6.9, 6.10. The human analyst is a **descriptive reference, not a baseline to beat**.
