---
title: Research questions
short_title: RQs
description: >-
  The research questions raised by the gap, with pre-registered hypotheses and
  nulls verbatim from the frozen post-consultation specification (§6.1).
---

(research-questions)=

:::{warning} Pre-experiment—not frozen
Nulls are quoted from the frozen specification (post-professor-consultation,
two-sided, paired). They become append-only at freeze (`v1.0-prereg`); before that,
they are design, not evidence.
:::

Hierarchical gatekeeping—RQ1, RQ2 gate; RQ8 follows; everything else is secondary
or descriptive. **At n = 10 (pilot) nothing is confirmatory; the pilot estimates
effects and validates the instrument. Confirmatory claims live in the scaled study
(N ≥ 80).**

## Confirmatory family (gate order)

::::{grid} 1 1 2 2

:::{card} RQ1—interface factor (gate)
Does the interface change executed-artefact success rate on geoprocessing tasks?

**H₀:** π_MCP = π_CG (two-sided, direction unspecified).

Paired exact McNemar on discordant tasks; bootstrap 95 % CI on ΔWSZ; Cliff's δ.
:::

:::{card} RQ2—enforcement-depth curve (gate)
Does WSZ rise with enforcement depth at the boundary (N1→N4)?

**H₀:** β_linear = 0 (linear contrast); secondary plateau **H₀:** WSZ(N4) − WSZ(N3) = 0.

Ordinal contrast on per-run WSZ; plateau contrast. Mechanism leg; only if the N-flag
is implemented (see [Experiment](../study/experiment.md)).
:::

:::{card} RQ8—silent corruption
Does enforcement ≥ N2 eliminate executable-but-invalid artefacts that codegen ships
silently?

**H₀:** silent-invalid rate (CG or N≤1) = silent-invalid rate (≥ N2).

Exact Fisher; odds ratio + CI. The GIS-specific causal claim; predicates double as
boundary checks, so the (enforced ∩ oracle) enumeration is mandatory pre-freeze.
:::

:::{card} RQ3—expressible-share moderation
Does the interface delta grow with task expressibility (P/A/C; low/med/high)?

**H₀:** paradigm × expressible-share interaction = 0.

Exploratory at 10 tasks; confirmatory only at scale. Cartography is the pre-registered
counter-case.
:::

::::

## Secondary family (Hochberg within family)

::::{grid} 1 1 2 2

:::{card} RQ6—reliability
Do arms differ in pass^4 / ICC?

**H₀:** pass⁴_MCP = pass⁴_CG. Small-sample exact; ICC by arm.
:::

:::{card} RQ4—failure taxonomy
Do arms distribute failures differently (interface-adjacent vs workflow-silent vs
hallucinated structure)?

**H₀:** multinomial distributions identical. Exact multinomial; double-coded
subsample, Cohen's κ ≥ 0.6.
:::

::::

## Descriptive family (estimates + CIs only; never p-vibes)

| ID | Question |
|---|---|
| RQ5 | Cost per *successful* task (requests, tool-calls, wall-clock; $ only with a stable price table) |
| RQ-E | Deployed-pattern arm (MCP + `execute_code`): bypass/collapse rate; ΔWSZ vs pure MCP |
| RQ-C | Code-as-driver arm (Python → typed MCP tools): ΔWSZ vs A and vs B; trajectory classification |
| RQ-PH | Human reference (GUI-first): WSZ_h, human_time_min, human_steps; same oracle; descriptive |
| RQ-I | Instrument integrity: 3× oracle determinism; log completeness; 0 silently dropped runs |

**Out of scope (pre-declared):** model × paradigm interaction; security frontier; VGI
moderator; human verification cost; live-vs-mock servers (the reference server is
deterministic and logged—declared assumption).

See [Hypotheses](../study/hypotheses.md) for the inferential contract that binds these RQs
together, and [Experiment](../study/experiment.md) for the arms that answer them.
