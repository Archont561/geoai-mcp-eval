---
id: GEO-020
title: Marimo GitHub Actions analysis client and DataFrame loader
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - analysis
  - marimo
  - refactor
milestone: m-5
dependencies:
  - GEO-015
  - GEO-017
  - GEO-019
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Move experiment analysis out of the CLI and into a clean Python analysis client (`experiment/src/experiment/analysis/`) designed for Marimo notebooks (`docs/analyses/experiment-analysis.md`).

Capabilities:

- `GitHubRunClient`: thin `gh` CLI wrapper with a local disk cache (`.cache/gh-runs/`) that downloads a run's single `experiment-run-<run_id>.zip` artifact by run ID or latest dispatch (and supports `load_zip(path)` for offline/local analysis).
- `RunDataset` / DataFrame projections computed directly from validated `TrialMeasurement` DTOs inside `RunArchive`:
  - `measurements_df()`: 1 row per trial (`run_id`, `task_id`, `paradigm`, `enforcement_level`, `repetition`, `task_success`, `predicate_score`, `silent_invalid`, `wall_seconds`, `llm_calls`, `tool_calls`, `repair_turns`, nullable token columns).
  - `predicates_df()`: flat binary `0/1` predicate matrix preserving strict cross-task zero semantics (never `NaN`, never imputed).
  - `cell_summary_df()`: per `task_id × paradigm × enforcement_level` aggregates (`n_trials`, `task_success_rate`, `predicate_score_mean`, `predicate_score_median`, `pass_at_k`, `silent_invalid_rate`).
  - `assertions_df()`: long-form per-assertion verdicts with `tier` (`trivial | spatial | value`) and `predicate`.
- Lazy trial inspection (`dataset.trial(key).transcript`, `.deliverable`) for drilling into specific failures in Marimo without eager loading.
- Keep `import-linter` Contract #9 enforced: `experiment.analysis` never imports `llm_cache` or `cache_key`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `experiment/src/experiment/analysis/` exposes `GitHubRunClient` (download + cache via `gh`, plus offline `load_zip`) and `RunDataset` DataFrame projections (`measurements_df`, `predicates_df`, `cell_summary_df`, `assertions_df`).
- [ ] #2 `predicates_df()` preserves strict 1:1 assertion-to-predicate validation and cross-task zero semantics (missing/failed checks score `0`, unknown assertions fail loudly).
- [ ] #3 `import-linter` contract confirms `experiment.analysis` never imports `experiment.adapters.llm_cache` or `experiment.domain.cache_key`.
- [ ] #4 `docs/analyses/experiment-analysis.md` uses the English ontology terms and demonstrates loading via `GitHubRunClient` while keeping GitHub Pages builds offline-safe.
- [ ] #5 Unit tests cover cached `gh` downloads (mocked subprocess), offline zip loading, all four DataFrame projections, and lazy trial drill-down.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Create `experiment/src/experiment/analysis/` (`github_client.py`, `dataset.py`, `__init__.py`) replacing legacy `experiment/src/experiment/analyze.py`.
2. Update `pyproject.toml` `[tool.importlinter]` Contract #9 to guard `experiment.analysis`.
3. Add unit tests for `GitHubRunClient` caching/offline loading and `RunDataset` DataFrame projections.
4. Update `docs/analyses/experiment-analysis.md` and verify strict MyST docs build (`pixi run tools run md` + docs check).
<!-- SECTION:PLAN:END -->
