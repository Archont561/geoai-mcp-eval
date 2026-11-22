---
title: Research questions — confirmatory and secondary
short_title: Research questions
description: >-
  Research questions and nulls from the frozen thesis specification, with
  hierarchical gatekeeping, secondary family, and descriptive family.
---

(fresh-rqs)=

# Research questions — confirmatory and secondary

**Status:** pre-implementation design specification (post-professor-consultation).
Nulls are quoted from the frozen post-consultation specification (§6.1).
**At n = 10 tasks nothing is confirmatory; the pilot estimates effects and
validates the instrument; confirmatory claims live in the scaled study (N ≥ 80).**

---

## Confirmatory family (gate order)

Hierarchical gatekeeping — RQ1, RQ2 gate; RQ8 follows; everything else is
secondary or descriptive.

### RQ1 — interface factor (gate)

*Does the interface change executed-artefact success rate on geoprocessing tasks?*

**H₀:** π_MCP = π_CG (two-sided, direction unspecified).
Paired McNemar (exact) on discordant tasks; bootstrap 95 % CI on ΔWSZ; Cliff’s δ.
**Gate** — stops inference chain otherwise.

### RQ2 — enforcement-depth curve (gate)

*Does WSZ rise with enforcement depth at the boundary (N1→N4)?*

**H₀:** β_linear = 0 (linear contrast); secondary plateau **H₀:** WSZ(N4) − WSZ(N3) = 0.
Ordinal contrast on per-run WSZ; plateau contrast. Mechanism leg; only if the
N-flag is implemented in the prototype (§6.2 note).

### RQ8 — silent corruption (gate)

*Does enforcement ≥ N2 eliminate executable-but-invalid artefacts that codegen ships silently?*

**H₀:** silent-invalid rate (CG or N≤1) = silent-invalid rate (≥ N2).
Exact Fisher; odds ratio + CI. The GIS-specific causal claim; predicates double
as boundary checks, so the (enforced ∩ oracle) enumeration is mandatory
pre-freeze.

### RQ3 — expressible-share moderation

*Does the interface delta grow with task expressibility (P/A/C; low/med/high)?*

**H₀:** paradigm × expressible-share interaction = 0.
**Exploratory at 10 tasks; confirmatory only at scale.** Cartography is the
pre-registered counter-case.

---

## Secondary family (within-family correction: Hochberg)

### RQ6 — reliability

*Do arms differ in pass^4 / ICC?*

**H₀:** pass⁴_MCP = pass⁴_CG.
Small-sample exact; ICC by arm.

### RQ4 — failure taxonomy

*Do arms distribute failures differently (interface-adjacent vs workflow-silent vs hallucinated structure)?*

**H₀:** multinomial distributions identical.
Exact multinomial; double-coded subsample, Cohen’s κ ≥ 0.6.

---

## Descriptive family (estimates + CIs only, never p-vibes)

| ID | Question |
|---|---|
| **RQ5** | cost per *successful* task — report requests/tool-calls/wall-clock (and $ only if the backend exposes a stable price table — assumed absent for BigPickle free); bootstrap CIs. Honest note: token accounting may be missing; proxies only, never fabricated zeros. |
| **RQ-E** | deployed-pattern arm (MCP + `execute_code`) — bypass/collapse-rate; ΔWSZ vs pure MCP. Descriptive; bounds internal validity; carries the “were plugins pure?” observation. |
| **RQ-C** | code-as-driver arm (Python → typed MCP tools) — does orchestrating typed tools from code beat direct typed calls? ΔWSZ vs arm A and vs arm B (CIs); trajectory classification (typed-only/code-only/mixed). |
| **RQ-PH** | human reference — WSZ_h, human_time_min, human_steps; same oracle; descriptive. |
| **RQ-I** | instrument integrity — 3× oracle determinism on fixed artefacts; log completeness; 0 silently dropped runs; validator coverage of the task suite. |

---

## Out of scope (pre-declared)

model × paradigm (RQ9-old), security frontier (RQ10-old), VGI moderator (RQ11-old),
human verification cost (RQ12-old), live-vs-mock servers (RQ7-old: the reference
server is deterministic & logged — declared assumption).
