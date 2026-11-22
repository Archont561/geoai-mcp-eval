---
title: Gap — the empty cell
short_title: Gap
description: >-
  The gap in existing research: no study holds engine + model + data + oracle
  constant while manipulating only the integration interface and scoring executed
  GIS artefacts against ISO 19157 predicates.
---

(fresh-gap)=

# Gap — the empty cell

**Status:** pre-implementation design specification (post-professor-consultation).

---

## The empty cell (verbatim logic)

No study holds engine + model + data + oracle constant, manipulates *only* the
integration interface (typed MCP vs CodeGen), and scores executed GIS artefacts
against ISO 19157 predicates under repetition (pass^k), with contamination-aware
strata and preregistered tolerances.

## Why it has survived so far

(i) it is expensive (N engine runs × N tasks × N interfaces);
(ii) the answer is telegraphed directionally (GeoJSON 97/86; MCPGAUGE
degradation);
(iii) scoring asymmetry — code artefacts are freely executed, tool artefacts need
per-tool predicates;
(iv) catalog-design confounds make “MCP” ill-defined as a treatment;
(v) GIS semantics (CRS/topology/MAUP) punish judges — you must build real
predicates [iso19157; egenhofer1991; openshaw1984maup].

## Nearest neighbours and what they leave open

| # | Work | What it fixes | What remains open |
|---|---|---|---|
| 1 | GeoJSON Agents [luo2026geojson] | head-to-head interfaces | domain-closed (GeoJSON), FC≠MCP protocol, multi-agent confound, no spatial oracle |
| 2 | GeoContra [geocontra2026] | contract+repair for codegen | no MCP arm; task-template contracts; not the interface factor |
| 3 | GeoAgentBench [yu2026geoagentbench] | executed sandbox + PEA | tool-calling only; no codegen arm; catalogue is atomic, not typed-MCP-as-shipped |
| 4 | GISAgentBench [gisagentbench2026] | artefact ground truth; tolerances | no interface manipulation; binary file match, not ISO predicates; no repetition |
| 5 | MCPGen [yang2026mcpgen] | executed MCP *projects*; <57 % e2e | evaluation of project generation, not GIS, not interface-as-factor |
| 6 | DynamicMCPBench [kaminski2026dynamicmcpbench] | live-server effect scoring, pass^3 | general domains; not GIS; not interface-as-factor; single-config |
| 7 | MCPEvol-Bench [liu2026mcpevolbench] | evolution robustness, 123 servers | different question (drift), enables your frozen-catalogue justification |
| 8 | ReliabilityBench [gupta2026reliabilitybench] | pass^k methodology | scheduling/travel/support; no GIS; no interface factor |
| 9 | Shingleton & Basiri [shingleton2025geoquality] | ISO-style quality for LLM geoparsing | geoparsing/routes scale only; not multi-tool GIS artefacts |
| 10 | ichms2026_mcp_geodata [ichms2026_mcp_geodata] | MCP *discovery* vs humans | metadata search, not artefact execution; open the adjacent cell |

## Adversarial floor test

Any 2026–2027 work doing GIS artefact MCP-vs-codegen with executed ISO scoring
appears before freeze → this spec’s novelty must be re-scoped to the mechanism
leg (C3) and the instrument (C1); C2 becomes replication, still worthwhile.
