---
title: Literature review — condensed
short_title: Literature review
description: >-
  Condensed literature review for the frozen thesis specification. Every claim
  keyed to bibliography.bib (81 entries).
---

(fresh-lit-review)=

# Literature review — condensed

**Status:** pre-implementation design specification (post-professor-consultation).

Read `[key]` = provenance-anchored in `bibliography.bib`. Corpus = 81 entries
(69 primary + 7 gap-tested + 5 added 2026-11-16 with explicit sign-off:
`barr2015oracle`, `yang2026mcpgen`, `kaminski2026dynamicmcpbench`,
`liu2026mcpevolbench`, and `paschalides2026mcpgranite` — the catalogue-sizing
cite: tool-interface granularity as a controlled variable, 4-tool optimum, +16.4
pp task completion vs fine-grained primitives).

---

## Group A — GIS canon & standards (oracle vocabulary)

ISO 19157 (data quality elements; superseded 2013→19157-1:2023, element names
still the mapping vocabulary) [iso19157]; geometry schema & topology
[iso19107]; metadata [iso19115]; Egenhofer’s DE-9IM [egenhofer1991]; uncertainty
of spatial data [zhangGoodchild2002; goodchildGopal1989; burrough2015;
longley2015]; error propagation in GIScience [heuvelink1998]; semantics
[kuhn2005; kuhn2012]; MAUP [openshaw1984maup]; Jenks classification
[jenks1971]; cartography canon [slocum2009; maceachren1992; monmonier2018;
harrowerBrewer2003]; review ISO-style quality for LLM outputs
[shingleton2025geoquality].

Establishes that the oracle’s predicate families are *standard GIScience quality
elements*, not bespoke checks.

---

## Group B — Autonomous GIS (what agents demonstrably do)

Vision & autonomy levels [li2023autonomous; li2025autonomous]; data-retrieval
agent [ning2025autonomous]; QGIS-as-tools multi-agent, fine-tuning for execution
success (100 % exec / 87.5 % semantic, ceiling degrades with complexity)
[mansourian2026multiagent]; code-generation multi-agent with RAG over 8 729
syntax docs (gains +7.59–26.09 %, ablation −4.4–9.3 %) [wu2025geocolab]; MCTS
over programs [chen2024geoagent]; end-to-end 1 800 controlled runs, Cliff’s δ,
Kendall τ = 0.94; single-agent ReAct > dual-agent on every cloud backend, except
locally-deployed 14B gains from orchestration [han2026gisclaw]; 1 778 expert
reasoning steps, step-wise scoring [shabbir2025thinkgeo]; open-weight
cost–capability frontier (≈ 93 % of Claude’s capability at 11.6× lower cost)
[diazireland2026geonatureagent]; maturity snapshots
[liang2026geoagentic; openearthagent2026].

---

## Group C — Protocols (what MCP *is* and *how fragile* it is)

Normative spec [anthropicMCP]; ecosystem reviews
[nargund2025mcp; strickland2026pareto; mastouri2025automcp] (88.6 % REST-wrapped
servers; median 19 % ops exposed; catalogs are edited artefacts; generated
servers 76 % → 94.2 % after repair); 16-lifecycle-activity threat taxonomy, 16
scenarios, four attacker classes [hou2025mcp]; three protocol-level flaws +
PROTOAMP (847 scenarios; MCP amplifies +23–41 % attack success; ATTESTMCP
52.8→12.4 %) [maloyan2026breaking]; MSB — 12 attacks, 2 000 instances, NRP
robustness metric; stronger models *more* vulnerable [zhang2025msb];
error-accumulation theory O(√T), re-grounding ≈ every 9 steps
[fan2026infofidelity]; OGC lineage [ogcWps2; ogcApiProcesses]; adjacent client
protocol [agentClientProtocol].

---

## Group D — General tool-use & agent benchmarks (instrument canon + grim baseline)

τ-bench pass^k [yao2024taubench]; ReliabilityBench surface R(k,ε,λ)
[gupta2026reliabilitybench]; MCP-Atlas (claim-coverage@0.75; 63.3 % cognitive
failures) [bandi2026mcpatlas]; MCP-Bench (28 servers/250 tools; cross-tool
coupling) [wang2025mcpbench]; LiveMCP-101 (7 failure modes; TSR/ARS)
[yin2025livemcp]; MCPToolBench++ (AST score; 4 k servers; scaling)
[fan2025mcptoolbench]; LiveMCPBench (retrieval ≈ ½ of failures)
[mo2025livemcpbench]; MCP-Universe (frontier 29–44 %; dilution)
[luo2025mcpuniverse]; MCPGAUGE (integration degrades; 4 axes)
[song2025helpor]; OGSAgent’s GeoMCP (publish–find–bind; nearest *design*
precedent, NOT evidence of effectiveness) [ogsagent2026]; eval discipline —
grade outcome not trajectory; CORE-Bench 42→95 % after grader audit
[anthropic2026evals]. **2026 wave:** MCPGen, DynamicMCPBench, MCPEvol-Bench (§2)
[yang2026mcpgen; kaminski2026dynamicmcpbench; liu2026mcpevolbench].

---

## Group E — GIS-agent benchmarks (the competitive set)

GeoAnalystBench (50 expert tasks; validity vs CodeBLEU “right shape wrong
numbers”; 95 %/0.39 ceiling) [zhang2025geoanalystbench]; GeoAgentBench (PEA,
Last-Attempt Alignment; Plan-and-React beats Direct/ReAct/Plan-and-Solve;
≈117–133 tools, number drifts between preprint and .bib — cite published
version) [yu2026geoagentbench]; GISAgentBench (349 tasks; strict tolerances; 32.7
% best; IoU ≥ 0.5 entity F1) [gisagentbench2026]; GeoBenchX (unsolvable-task
rejection scoring) [krechetova2025geobenchx]; GeoContra (contracts+repair; +26.6
pp; 7 079 tasks/11 models/600 runs) [geocontra2026]; ThinkGeo; OpenEarthAgent;
GeoNatureAgent (cost–capability) [shabbir2025thinkgeo; openearthagent2026;
diazireland2026geonatureagent].

---

## Group F — MCP × GIS (the thin intersection everyone claims and nobody operationalised)

GeoJSON Agents head-to-head [luo2026geojson]; GNSS tool-exposure guidance
[tool_exposure_gnss_2026]; GeoMCP server design [ogsagent2026]; discovery-MCP
benchmark (agents ≈ humans on parts; exact-match; better on parts, worse on
others) [ichms2026_mcp_geodata]; ICHMS cluster [gis-mcp-server-cluster-2026].

What exists: systems and specs. What does not: executed-artefact comparison on
the interface axis with ISO predicates (§5).

---

## Group G — Cartographic judgement (C-family tasks)

ColourBrewer compliance [harrowerBrewer2003]; intent-driven colour
[gauslaa2026intentcolour]; choropleth LLM case [pannoon2025choropleth]; visual
variables [maceachren1992; slocum2009]; map-abuse canon [monmonier2018]; Jenks
GVF [jenks1971]. Consumed as *descriptors*, never as pass/fail.

---

## Group H — Method

DSR [peffers2007design]; statistics: paired binary tests, mixed models,
gatekeeping, MDE [anthropic2026evals]; reproducibility practice
[nust2018; konkol2019]; instrument/usability framing [nivala2008]; reproducibility
of agent runs via pass^k (Group E/D).

---

## Synthesis in one line

The field is code-generation-first for GIS [li2023autonomous; li2025autonomous;
wu2025geocolab] and MCP-first only as *design* [ogsagent2026]; every benchmark
manipulates models or architectures, none manipulates **interface paradigm** with
executed, ISO-scored artefacts — and the 2026 wave only sharpened execution
difficulty and liveness, not the factor (§5).
