---
title: Implementation status
short_title: Implementation
description: >-
  Current implementation and the engineering constraints carried into the run
  (pins, logging, deviations); study results remain unfrozen.
---

(implementation)=

:::{warning} Pre-experiment—not frozen
The repository includes an experiment CLI scaffold and a QGIS plugin prototype. The
study protocol and results remain unfrozen; this page distinguishes implemented
scaffolding from planned or unverified study behavior.
:::

## Implementation snapshot (state supplied; date not independently verified)

| Layer | State |
|---|---|
| Repository scaffold (pixi, Tasknest, alint, rumdl, Vale, CI, Pages) | Present; MyST docs added (this site) |
| Experiment code (`experiment/`) | Typer CLI and smoke tests; pilot task suite not frozen |
| Task suite | Not frozen; YAML schema v1 designed, tasks not written |
| MCP server / catalogue | Not built; catalogue constant hash pending |
| Oracle / checkers library | Not built; determinism gate untested |
| Model access | OpenCode-hosted BigPickle (free tier; daily request limit; no durable pinning, seed or token accounting) |
| Human baseline | Not run |

## Engineering constraints (carried into the run)

- **Model:** log `model_id`, `run_date`, driver hash, temperature on every record;
  provider drift is unmeasured variance bounded by r = 4; results are never reported as
  "BigPickle shows…" beyond this scope.
- **Runtime:** Python 3; `mcp` client; `geopandas`, `shapely`, `pyproj`, `rasterio`,
  `pyogrio`; QGIS LTR via a dedicated profile; PROJ/GDAL versions pinned and recorded.
- **Environment:** `pixi install --locked`; the `experiment` feature is currently
  included in the default environment with tooling. The docs environment has its own
  solve group. Split the GIS stack before measurement runs if it affects tooling
  reproducibility. Nothing runs Python via `uv`/`pip`/`venv` inside this repo.
- **Determinism:** oracle 3× identical verdicts on fixed artefacts is a blocking gate.
- **Logging:** independent fresh session per run; wall-clock timestamps; the run directory `results/<run_id>/` archived automatically; 0 silently dropped runs; logged artefacts are never edited
  post-hoc.
- **Measurement limits:** token accounting may be missing (no stable price table assumed);
  proxies only, never fabricated zeros.

## Deviations log

No deviations are recorded yet—nothing has been run. When the study executes, every
deviation from the registered protocol will be documented here, with its rationale and
its blast radius. Silence means fidelity, not absence of drift to look for.

## What appears at freeze

The frozen catalogue hash and validator results, the checkers' coverage of every oracle
type in the suite, the pilot report (instrument health, wall-clock, failure heuristics),
and the `v1.0-prereg` preregistration tag (specification + task checksums + seed table)
will appear here as recorded facts, not plans. Until then this page is a statement of
intent—see [Reproducibility](../reproducibility.md) for the contract.
