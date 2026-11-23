---
title: Context — WHY NOW and DEFINITIONS
short_title: Context
description: >-
  Observed state of the field (numbers kept honest and cited) and operative
  definitions for the frozen thesis specification.
---

(fresh-context)=

# Context — WHY NOW and DEFINITIONS

**Status:** pre-implementation design specification (post-professor-consultation).

---

## 2. WHY NOW — observed state of the field (numbers kept honest and cited)

- Real-world MCP servers defeat frontier models: GPT-5 43.7 %, Grok-4 33.3 %,
  Claude-4.0-Sonnet 29.4 %; Cursor-type products do not beat plain ReAct; more
  servers → accuracy dilution [luo2025mcpuniverse]. Most models sit at 30–50 %
  task success on realistic tool spaces; retrieval errors account for ~half of
  all failures [mo2025livemcpbench].
- τ-bench established pass^k: GPT-4o < 25 % at k=8 (retail) [yao2024taubench];
  per-trial success flatters multi-trial reliability by 20–40 pp
  [gupta2026reliabilitybench].
- GIS-specific ceilings: best executed-artefact agent ≈ 32.7 % (tolerance-strict)
  [gisagentbench2026]; contract+repair raises spatial correctness by ≈ +26.6 pp
  in codegen [geocontra2026] — i.e., enforcement works where it is applied.
- The one head-to-head across interfaces: code generation 97.14 % vs function
  calling 85.71 % (GeoJSON world, GPT-4o) [luo2026geojson] — a *different*
  domain, a *different* protocol, judged non-spatially.
- MCPGAUGE (6 commercial LLMs, 30 tool suites, ~20 k calls): integration
  **degrades** effectiveness across domains — MCP is not a free win
  [song2025helpor].
- 2026 wave narrows the residual gap: executable MCP artefacts remain hardest —
  < 57 % end-to-end (MCPGen; schema-binding errors ≈ 31.9 % of traces)
  [yang2026mcpgen]; live-server effect-scored accuracy ≈ 50 % ceiling with
  pass^3 collapse across chain length (39 % → 13 %)
  [kaminski2026dynamicmcpbench]; server evolution degrades frontier models by
  13–14 pp [liu2026mcpevolbench].
- Practitioners are shipping hybrids (MCP inside code execution) and nobody has
  measured which configuration this produces for GIS
  [anthropic2026evals; anthropicMCP].

---

## 3. DEFINITIONS (operative for this specification)

- **GIS** — system capturing, storing, manipulating, analysing and presenting
  geographic information [burrough2015; longley2015]; GIScience canon supplies
  the semantics used here (accuracy, topology, semantics, MAUP)
  [goodchildGopal1989; zhangGoodchild2002; kuhn2005; openshaw1984maup].
- **Geoprocessing task** — a bounded spatial operational goal with a checkable
  deliverable: output artefact(s) of defined geometry type, CRS, schema and value
  ranges (e.g. “buffer 500 m around schools, clip to district, dissolve, count”).
  Tasks here are P/A/C-stratified (§6.4): **P** reparation/IO, **A** nalysis,
  **C** artography.
- **Spatial phenomenon / georeferencing** — coordinates in an Earth reference
  frame; operations inherit axis-order, units and CRS semantics
  [iso19107; egenhofer1991; iso19115].
- **LLM agent** — an LLM acting in a loop (plan → call tool → observe →
  continue) that may act on the world via tools [anthropicMCP;
  nargund2025mcp; li2025autonomous].
- **Tool / function** — a named, typed operation with machine-checkable argument
  schema exposed to the agent (JSON Schema for MCP) [anthropicMCP;
  agentClientProtocol].
- **MCP (Model Context Protocol)** — JSON-RPC 2.0, stateful capability
  negotiation (initialize → tools/resources/prompts ↔ roots/sampling/elicitation)
  [anthropicMCP]. OGC-lineage context: WPS 2.0 / OGC API Processes are the
  standards ancestors [ogcWps2; ogcApiProcesses].
- **Catalogue** — the fixed, documented tool inventory an agent may invoke. *In
  this experiment the catalogue is constant; the middleware is variable.*
  Catalogue design, size and exposure are known confounds
  [mastouri2025automcp; tool_exposure_gnss_2026; strickland2026pareto;
  paschalides2026mcpgranite].
- **Typed tool call** — one schema-validated invocation of a catalogue tool; its
  result is structured data, not free text.
- **Code generation (CodeGen)** — the agent writes and executes Python
  (PyQGIS/GeoPandas/Shapely/Rasterio/GDAL) with arbitrary libraries; correctness
  is judged only post-hoc by the oracle.
- **Contract** — the machine-checkable specification bound to a call: (i)
  signature constraints (types, enums, ranges, units), (ii) domain constraints
  (CRS membership/axis-order policy, geometry validity, extent sanity, plausibility
  ranges), (iii) postconditions/invariants (artefact CRS == requested,
  feature-count delta, mandatory non-null fields, workflow invariants).
- **Enforcement depth N (independent variable; ordinal)** — a middleware
  property, not a model property and not a catalogue property:
  - N1 declarative: prose only; schema published, not enforced; no server-side
    check.
  - N2 syntactic gate: JSON-Schema validation, enums/units/CRS membership;
    deterministic reject with `error_code` + expected/got; call not executed.
  - N3 semantic gate + bounded repair: N2 + domain checks (axis-order, `is_valid`,
    extent vs inputs, plausibility); on violation → structured feedback →
    **one** repair attempt; second failure = task failure.
  - N4 transactional: N3 + postcondition re-verification of the artefact (CRS,
    feature counts, extent, schema, mandatory non-nulls); workflow invariants
    between steps; all-or-nothing step semantics; full audit log.
  - (N0 — CodeGen control arm: checks live only in the post-hoc oracle.)
- **Oracle (*test oracle*)** — the decision procedure mapping
  actual → verdict `(pass, value, tolerance)` functions
  [barr2015oracle]. Not gold truth; not the validator; not a metric. The ISO
  19157 elements (completeness, logical consistency [DE-9IM/`iso19107`],
  positional accuracy, thematic accuracy, temporal quality, usability)
  operationalised as executable predicates [iso19157; egenhofer1991;
  shingleton2025geoquality]. Predicate-vs-invariant oracles often need *no stored
  ground truth*; where a reference artefact/tolerance exists it is consumed as
  one input.
- **Ground truth** — expected state/values: reference artefacts, tolerances,
  task-card facts. **Validator** — N3/N4’s runtime twin of the oracle; the
  (enforced ∩ oracle) set is enumerated pre-freeze so “testing on one’s own
  checks” is auditable. **Metric** — aggregation over oracle verdicts (below).
- **WSZ (task success rate)** — task success: 1 iff **all** assertions
  for the task pass on the executed artefact (strict; no partial credit inside
  the binary).
- **OQS (mean predicate score)** — continuous: mean predicate-pass fraction
  per run ∈ [0,1] (report alongside WSZ).
- **pass^k** — P(all k independent trials succeed) [yao2024taubench;
  gupta2026reliabilitybench]; here k = r = 4 repeats/cell.
- **ICC** — intraclass correlation (task vs run variance), target-like reliability
  of the instrument.
- **MDE** — minimum detectable effect; this design is powered for ≈ 11.5 pp
  differences only, and is honest about it (§6.8).
- **Contamination** — public tasks may sit in pretraining; strata: `inherited`
  vs `constructed` (§6.4), analysed separately.
- **Silent corruption** — executable, non-crashing artefact that is geographically
  invalid (CRS/units/NoData/aggregation/zonation — MAUP)
  [openshaw1984maup; geocontra2026].
- **Expressible share** — fraction of the task expressible as one typed-tool call
  (low/med/high; moderator for RQ3); cartography is the pre-registered
  counter-case.
- **Collapse rate** (arm C only) — fraction of runs where the model bypasses
  typed tools entirely (code-only trajectory); classifier built into the results
  contract.
- **Head-to-head** — any arm-vs-arm comparison; only (A) vs (B) is confirmatory;
  (C), (D) are mechanism/realism descriptives.
- **Arm H (human reference)** — not an arm in inference; a descriptive
  ceiling/floor witness (§6.9).
- **Repair turns** — count of N3 repair rounds per run (0–1 by construction).
- **Schema-violation rate** — fraction of calls rejected at N2+; **bypass/no-output
  rate** — fraction of runs with zero parseable tool calls or no artefact.
