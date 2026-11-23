---
title: Reproducibility
short_title: Reproducibility
description: >-
  The run contract: environment, pins, freeze order, and what never enters the
  repository.
---

(reproducibility)=

## Environment

```bash
pixi install --locked        # environment from the committed pixi.lock
pixi run tools ls            # task graph sanity
pixi run tools check         # alint + ruff + pytest + rumdl (offline gate)
pixi run tools run prose     # Vale prose gate (downloads presets; network required)
```

- **pixi only** for Python environments. No `uv`, `pip`, `requirements.txt`, `venv`.
- Python 3.12–3.13. Bun is pinned for agent-skill/Backlog.md CLIs only.
- The `docs` feature uses its own solve group. At present, the `experiment` feature is
  included in `default` alongside tooling; split it into a dedicated solve group before
  measurement runs if GIS dependency growth or incompatibilities affect the automation environment.
- This documentation site builds with the pinned MyST CLI:

```bash
pixi install --locked --environment docs
pixi run --environment docs -- npm exec --yes --package=mystmd@1.13.0 -- myst build --html --strict --ci
```

- The `docs/analyses/` pages are raw marimo notebooks rendered at build time through
  the `jupyter-book-marimo` executable plugin (registered in `docs/myst.yml`). The GIS.SE page
  uses an embedded public-source snapshot, not a committed API cache; its retrieval date and
  values are not independently verified, so validate them before relying on the analysis.
  The experiment-analysis page embeds clearly labelled illustration rows until pinned runs
  execute; it holds no pilot data yet.

## Pins and determinism

| Item | Contract |
|---|---|
| Model | OpenCode-hosted BigPickle; pin what the provider exposes (`model_id`, `run_date`, driver hash, temperature); accept the rest as bounded variance (r = 4) |
| Engine | QGIS LTR, dedicated profile; PROJ/GDAL versions pinned and recorded |
| Python libs | `geopandas`, `shapely`, `pyproj`, `rasterio`, `pyogrio` (locked via pixi) |
| Oracle | 3× determinism gate on fixed artefacts—blocking, pre-freeze |
| Randomisation | stratum-interleaved order; seed table frozen with `v1.0-prereg` |
| Runs | N ≥ 80 tasks × r = 4 (scaled); 200-run pilot ceiling as budgeted |

## What is never in this repository

- Private datasets, fixtures with personal data, unpublished results, run archives,
  experiment caches, or task-suite artefacts outside the registered freeze process.
  The documented Stack Exchange aggregates are public-source research context with
  CC BY-SA 4.0 attribution, not experiment run data.
- The thesis, its literature review, and its data analyses—they live in the
  surrounding workspace, not here.
- Secrets and API tokens—the model provider is called with environment variables,
  never committed config.

`docs/_build/` is gitignored; the built site deploys from CI artifacts, never from a local build.

## Freeze and re-verification

- Tag `v1.0-prereg` = specification amendment state + task checksums + seed table.
- Any post-freeze change to tolerances, hypotheses or stop-rules **invalidates the run
  log** and must ship as a new preregistration revision, never a silent edit.
- Changes to this site are gated in CI (Markdown, prose, strict MyST build) on every
  pull request.

## This site's own reproducibility

Pages are plain MyST Markdown; `docs/bibliography.bib` is a dated snapshot of the source
corpus; `robots.txt`, `sitemap.xml`, `llms.txt` and `llms-full.txt` are static files
served at the site root exactly as committed. The raw analyses execute at build
time; the outputs are baked into static HTML and hydrate in the browser.
