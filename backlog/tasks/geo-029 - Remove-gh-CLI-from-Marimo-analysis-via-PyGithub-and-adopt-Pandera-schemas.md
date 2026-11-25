---
id: GEO-029
title: Remove gh CLI from Marimo analysis via PyGithub and adopt Pandera DataFrame schemas
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
updated_date: '2026-11-25T00:00:00Z'
labels:
  - analysis
  - marimo
  - dependencies
  - github
  - pandera
milestone: m-5
dependencies:
  - GEO-020
  - GEO-024
ordinal: 29000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Eliminate the `gh` CLI subprocess dependency from `experiment.analysis` and Marimo notebooks (`docs/`) by replacing `gh` shell-outs in `GitHubRunClient` with **`PyGithub`** (plus `httpx` streaming artifact downloads and `filelock` cache safety), and replace manual pandas column-tuple/shape boilerplate in `experiment.analysis.dataset` with declarative **`pandera`** `DataFrameModel` schemas.

### Current state & motivation

1. **Unwanted `gh` binary prerequisite inside Marimo (`experiment/src/experiment/analysis/github_client.py`):**
   - `GitHubRunClient` currently shells out to `gh run list --workflow ... --json ...` and `gh run download <run_id> ...` via `experiment.adapters.subprocess_runner`.
   - Running Marimo notebooks (`docs/`) in clean Python/Pixi environments, CI docs builds, or researcher laptops fails unless the external `gh` CLI binary is separately installed and authenticated.
   - `GitHubRunClient` also duplicates manual JSON parsing (`WorkflowRunSummary.from_gh_dict`) and unguarded `.cache/gh-runs/` directory extraction.

2. **Hand-rolled pandas DataFrame schema enforcement (`experiment/src/experiment/analysis/dataset.py`):**
   - ~70 lines of module-level `MEASUREMENT_COLUMNS`, `PREDICATE_KEY_COLUMNS`, `CELL_SUMMARY_COLUMNS`, and `ASSERTION_COLUMNS` tuples and ad-hoc column ordering/dtype checks are maintained manually alongside `RunDataset` builders.

### Target architecture

1. **Pure-Python GitHub Actions client (`PyGithub` + `httpx` + `filelock`):**
   - Add `PyGithub` (`>=2.6,<3`) and `filelock` to both `[feature.experiment.pypi-dependencies]` and `[feature.docs.pypi-dependencies]` in `pixi.toml` (and `experiment/pyproject.toml`).
   - Refactor `experiment/src/experiment/analysis/github_client.py` so `GitHubRunClient` uses `github.Github(auth=Auth.Token(token))` (reading `GITHUB_TOKEN` / `GH_TOKEN`, or accepting an explicit `token` / injected `github.Github` client for testing, with unauthenticated fallback for public read-only listing where GitHub API permits).
   - List workflow runs via `repo.get_workflow(workflow).get_runs(...)` and resolve the single `experiment-run-*.zip` artifact via `run.get_artifacts()`.
   - Download the artifact archive stream via `httpx` (honoring GitHub's 302 redirect to Azure Blob Storage without forwarding the `Authorization` header cross-host), extract under a `filelock.FileLock` inside `.cache/gh-runs/<run_id>/`, verify SHA-256 integrity via `RunArchive.verify_all()`, and preserve the `cache_policy` (`"use"` / `"refresh"`) contract.
   - Resolve default `owner/repo` cleanly from an explicit `repo` argument, `GITHUB_REPOSITORY` env var, or `experiment.toml` (zero `gh` subprocess calls anywhere in `experiment.analysis` or `docs/`).

2. **Declarative DataFrame schemas (`pandera`):**
   - Add `pandera` to `[feature.experiment.pypi-dependencies]` and `[feature.docs.pypi-dependencies]`.
   - Define typed `pandera.pandas.DataFrameModel` schemas in `experiment/src/experiment/analysis/dataset.py` (or `schemas.py`):
     - `MeasurementTableSchema`
     - `PredicateMatrixSchema`
     - `CellSummarySchema`
     - `AssertionTableSchema`
   - Validate and coerce DataFrames returned by `RunDataset.measurements()`, `predicates()`, `cell_summary()`, and `assertions()` through Pandera (`coerce=True`), replacing manual `*_COLUMNS` column-ordering and dtype boilerplate.

3. **Architectural enforcement (zero `gh` / `subprocess` in `experiment.analysis`):**
   - Add an `import-linter` contract (or `test_architecture.py` rule) forbidding `experiment.analysis` from importing `subprocess` or `experiment.adapters.subprocess_runner`, guaranteeing Marimo analysis remains 100% pure Python with no external `gh` CLI dependency.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `experiment/src/experiment/analysis/github_client.py` uses `PyGithub` (+ `httpx` streaming download and `filelock`) to list workflow runs and download/cache `experiment-run-*.zip` artifacts with zero `gh` CLI invocations and zero `subprocess` imports.
- [x] #2 `GitHubRunClient` supports `token=` parameter, `GITHUB_TOKEN` / `GH_TOKEN` environment variables, and injected `PyGithub` / `httpx` test doubles, handles GitHub artifact redirect downloads cleanly, verifies `RunArchive.verify_all()`, and honors `CachePolicy` (`use` / `refresh`).
- [x] #3 `experiment/src/experiment/analysis/dataset.py` validates `measurements()`, `predicates()`, `cell_summary()`, and `assertions()` DataFrames via `pandera` `DataFrameModel` schemas, replacing manual column-list and dtype boilerplate.
- [x] #4 `PyGithub`, `httpx`, `filelock`, and `pandera` are declared in both `[feature.experiment.pypi-dependencies]` and `[feature.docs.pypi-dependencies]` so Marimo notebooks in `docs/` run without `gh` installed.
- [x] #5 An `import-linter` contract (and `test_architecture.py` check) forbids `experiment.analysis` from importing `subprocess` or `experiment.adapters.subprocess_runner`.
- [x] #6 Marimo notebooks and docs referencing `GitHubRunClient` document token-based auth (`GITHUB_TOKEN` / `GH_TOKEN`) instead of `gh auth login`, and tests verify mocked `PyGithub` + `httpx` downloads, cache refresh, corruption re-download, and Pandera schema enforcement.
- [x] #7 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, `97/97` `alint` rules passing, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Add dependencies to `pixi.toml` & `experiment/pyproject.toml`:** Add `PyGithub`, `httpx`, `filelock`, and `pandera` to `experiment` and `docs` features and refresh `pixi.lock`.
2. **Refactor `analysis/github_client.py` to `PyGithub` + `httpx`:** Replace `CommandRunner` / `gh` CLI calls with `PyGithub` workflow-run & artifact listing, `httpx` streaming zip download (redirect-safe auth handling), `filelock` cache locking, and `RunArchive.verify_all()` validation.
3. **Adopt `pandera` in `analysis/dataset.py`:** Define `DataFrameModel` schemas for measurements, predicates, cell summaries, and assertions and validate all `RunDataset` projections through them.
4. **Enforce zero-`subprocess` boundary & update docs/tests:** Add `import-linter` forbidden contract blocking `subprocess` / `subprocess_runner` from `experiment.analysis`, migrate `test_github_client.py` and `test_dataset.py` to mock `PyGithub`/`httpx` (zero `gh` fake runner), update Marimo docs, and pass `pixi run tools run fmt`, `check`, `md`, and `links`.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Completed in Step 4 (`GEO-029`):

- **Pure-Python GitHub Actions client (`experiment/src/experiment/analysis/github_client.py`)**: Replaced `gh` CLI subprocess calls with `PyGithub` (`github.Github` + `github.Auth.Token`), redirect-safe `httpx` artifact downloads (stripping `Authorization` on 302 redirects to Azure Blob SAS URLs), outer artifact zip unwrapping, `filelock`-guarded cache writes (`run_store.file_lock`), SHA-256 `RunArchive.verify_all()` with automatic re-download on cache corruption, and pure-Python `.git/config` / `GITHUB_REPOSITORY` repo resolution. Grouped injectable test collaborators cleanly in `GitHubTransport`.
- **Pandera `DataFrameModel` schemas (`experiment/src/experiment/analysis/dataset.py`)**: Defined `MeasurementTableSchema`, `PredicateMatrixSchema`, `CellSummarySchema`, and `AssertionTableSchema` plus `validate_predicate_matrix`, deriving `MEASUREMENT_COLUMNS`, `PREDICATE_KEY_COLUMNS`, `CELL_SUMMARY_COLUMNS`, and `ASSERTION_COLUMNS` from the schemas as a single source of truth and validating all `RunDataset` projections.
- **Manifests & Marimo docs**: Declared `PyGithub`, `httpx`, `filelock`, and `pandera` in both `[feature.experiment.pypi-dependencies]` and `[feature.docs.pypi-dependencies]` (`pixi.toml`) plus `experiment/pyproject.toml`, and updated `docs/analyses/experiment-analysis.md` to document token-based auth (`GITHUB_TOKEN` / `GH_TOKEN`) with zero `gh` CLI requirement.
- **Architecture contract**: Added `import-linter` contract `Analysis never shells out via subprocess or gh CLI` forbidding `experiment.adapters.subprocess_runner` and `subprocess` in `experiment.analysis` (verified in `test_architecture.py`), and added `github` and `pandera` to `experiment.domain`'s forbidden list.
<!-- SECTION:NOTES:END -->
