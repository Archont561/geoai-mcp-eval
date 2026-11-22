---
id: doc-007
title: Provenance & licensing
short_title: Provenance
description: >-
  Where the task bank evidence comes from (GIS StackExchange), how it was
  analysed, and the CC BY-SA 4.0 attribution obligations it carries.
type: guide
created_date: '2026-11-16T00:00:00Z'
---

(provenance)=

## Sources and date

| Item | Value |
|---|---|
| Source | GIS Stack Exchange API v2.3, `site=gis` |
| Retrieved | Date not independently verified |
| Scope | all-time tag counts; top questions by votes; English-only site |
| Method & full tables | [SE demand analysis](analysis.md)—this page carries the licensing obligations |

The supplied counts are not live data and have not been independently verified; the [raw notebook page](../../docs/analyses/gis-se-analysis.md) carries the embedded snapshot for offline inspection.

## Aggregate demand (selected, all-time counts)

| Tag | Count | Tag | Count |
|---|---:|---|---:|
| raster (broad) | 10 203 | spatial-join | 1 014 |
| coordinate-system | 8 647 | geocoding | 870 |
| field-calculator | 2 562 | zonal-statistics | 572 |
| dem | 2 113 | dissolve | 547 |
| distance | 1 620 | overlay | 512 |
| buffer | 1 533 | nodata | 277 |
| clip | 1 391 | choropleth | 147 |
| raster-calculator | 1 296 | jenks | 9 |
| merge | 1 284 | | |

The full method, frequency tables, the 27-row complexity ranking and catalogue-gap analysis live in the [SE demand analysis](analysis.md) page. Top-voted questions are roughly half **conceptual explainers** (EPSG:3857 vs 4326, datum
vs projection, axis order)—inherited tasks deliberately target exactly these confusion
points.

## Method in one paragraph

All-time counts per tag were pulled from the SE API (no time series, no geography
filter). Vote counts on the top-100 questions track conceptual confusion, not operational
need. Complexity tiers attached to tasks come from the task-suite difficulty rubric as expert
estimates, not measurements.

## Limitations

- Counts are all-time and tool-ecosystem-skewed (ArcGIS|QGIS dominate); no time series, no geography filter, English-only.
- Votes on the top-100 track **conceptual confusion**, not operational need; ~half the headline questions are CRS/datum explainers.
- Tag counts confound "asking" with "doing"; many high-count tags are installation/config/software topics, not tasks.
- Complexity tiers are expert estimates, not measurements; they anchor on the spec's rubric, pending pilot calibration.
- "Most common GIS tasks ranked by complexity" is not a number GIS.SE publishes; the analysis is a synthesis, not a dump.
- Licensing: inherited prompts must preserve attribution; constructed traps are the low-risk default.

## Licensing obligations (binding)

- Every inherited question is **CC BY-SA 4.0**. Attribution (link + licence) is recorded
  in each task's `provenance.source` / `provenance.license` fields; the complete
  attribution list will be deposited in the repository at freeze, listing every
  inherited item individually.
- Closed/locked questions may lack a license field; **do not derive from them**.
- Author-constructed tasks are **CC0-equivalent** (no attribution required); they carry
  `contamination: constructed` and remain the low-risk default where SE signal is absent.
- This site's prose is CC BY-SA 4.0; the repository code scaffold is MIT (see LICENSE).

## The load-bearing caveat

**GIS StackExchange selects tasks; it validates nothing.** Frequency measures demand,
never correctness. Artefact correctness is decided solely by the predicate oracle—see
[Experiment](../../docs/study/experiment.md) and [Hypotheses](../../docs/study/hypotheses.md).
