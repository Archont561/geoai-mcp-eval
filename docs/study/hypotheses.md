---
title: Hypotheses & inferential contract
short_title: Hypotheses
description: >-
  Nulls, decision rules, multiple-comparison discipline, and what counts as evidence—
  the contract that binds the research questions at freeze.
---

(hypotheses)=

:::{warning} Pre-experiment—not frozen
Append-only from freeze. Changing anything here after `v1.0-prereg` invalidates the
run log.
:::

## Two regimes of evidence

| Regime | n | What it yields | Claim status |
|---|---|---|---|
| Pilot (3 tasks × {A@N3, B} × r=2) | 12 runs + replications | Instrument validation; effect-size estimates | Never confirmatory |
| Pilot suite (10 tasks × 5 configs × r=4) | 200 runs (+160 stretch) | Estimates, CIs, instrument audits | Estimates only |
| Scaled study | N ≥ 80 tasks × r=4 | Tests of the confirmatory family | Confirmatory |

## Hypotheses and nulls (by gate order)

| Gate | Hypothesis | Null (verbatim) | Test |
|---|---|---|---|
| 1 | RQ1 interface factor | π_MCP = π_CG (two-sided) | Exact McNemar on discordant pairs; bootstrap 95 % CI on ΔWSZ (10 000 task resamples); Cliff's δ |
| 2 | RQ2 enforcement-depth curve | β_linear = 0 (linear contrast); plateau: WSZ(N4) − WSZ(N3) = 0 | Ordinal contrast; plateau contrast |
| 3 | RQ8 silent corruption | silent-invalid rate (CG or N≤1) = silent-invalid rate (≥ N2) | Exact Fisher; odds ratio + CI |
|—| RQ3 moderation (exploratory at pilot) | paradigm × expressible-share interaction = 0 | Stratified ΔWSZ with CIs |
| 4 | RQ6 reliability (secondary) | pass⁴_MCP = pass⁴_CG | Small-sample exact; ICC by arm |
| 4 | RQ4 failure taxonomy (secondary) | multinomial distributions identical | Exact multinomial; double-coded κ ≥ 0.6 gate |

## Discipline

- **Two-sided, paired.** Discordant tasks are the data; ties are uninformative.
- **Hierarchical gatekeeping** in the order RQ1 → RQ2 → RQ8 → (RQ6, RQ4). Failure at a
  gate stops the inference chain. Familywise α = .05; no peeks.
- **Hochberg** within the secondary family.
- **Descriptive** families (RQ5, RQ-E, RQ-C, RQ-PH, RQ-I) report estimates and CIs
  only—never p-values, never rankings ("MCP better/worse" is out of bounds at this stage).
- **Silent corruption** is the one latent GIS failure mode the design privileges:
  executable-but-invalid artefacts that pass casual inspection. Predicates double as
  boundary checks; the (enforced ∩ oracle) enumeration is mandatory pre-freeze.
- **No** mixed-effects models, power claims, or MDE claims at n = 10; underpowered
  tests are reported as uninformative, not as nulls.
- **Scale path**: at N ≥ 80, descriptive tags swap to confirmatory—same machinery,
  powered—with strata analyses retained and (if runs span weeks) a sequential-monitoring audit.

## What would count as evidence

At freeze, a claim of the form "the interface changes executed-artefact success" is
licensed only if RQ1 clears its gate with a two-sided exact McNemar on discordant
tasks, a bootstrap 95 % CI on ΔWSZ excluding (or including, direction-free) zero, and
the oracle-determinism + completeness gates (3× identical verdicts; 200/200 or N≥80×4
runs logged, no silent imputation). Anything weaker is reported as an estimate.

See [Experiment](experiment.md) for the design that produces those numbers, and
[Results](../findings/results.md) for where they will appear.
