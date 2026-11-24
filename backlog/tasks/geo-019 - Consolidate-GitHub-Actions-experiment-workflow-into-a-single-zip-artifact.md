---
id: GEO-019
title: Consolidate GitHub Actions experiment workflow into a single zip artifact
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - ci
  - workflow
  - refactor
milestone: m-5
dependencies:
  - GEO-015
  - GEO-018
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Refactor `.github/workflows/experiment.yml` so every completed dispatch (`preflight`, `smoke`, `pilot`) ends with **one** self-contained downloadable artifact (`experiment-run-<run_id>.zip`) instead of 16 separate artifacts.

Pipeline flow:

- `preflight`, `model`, and matrix `run` jobs upload short-lived inter-job handoff fragments (`retention-days: 1`).
- Fold summary rendering into the final `harvest` job: download all fragments, run `experiment archive pack` (merging into one `ExperimentRun`, running the 3-pass oracle determinism gate, asserting completeness, writing `summary.md` and `$GITHUB_STEP_SUMMARY`, and saving `experiment-run-<run_id>.zip`).
- Upload that single bundle artifact with `retention-days: ${{ inputs.retention-days }}`.
- Only when the bundle upload step succeeds (`steps.upload-bundle.outcome == 'success'`), run `experiment archive prune-ci` (with job-scoped `permissions: { contents: read, actions: write }`) to delete intermediate handoff artifacts for the run, leaving literally one artifact on the GitHub Actions run page.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `.github/workflows/experiment.yml` uses the refactored `experiment` Tasknest one-liners and folds summary rendering into `harvest`.
- [x] #2 `GitHubWorkflowAdapter.prune_run_artifacts(keep_name)` safely deletes intermediate artifacts for `$GITHUB_RUN_ID` only after bundle upload succeeds, and safely no-ops locally.
- [x] #3 Workflow-level `permissions` remain `contents: read`, with `actions: write` scoped strictly to the `harvest` job; `alint` and `actionlint` pass.
- [x] #4 A live GitHub Actions dispatch (`stage=smoke` and `stage=pilot`) completes cleanly and exposes exactly 1 artifact (`experiment-run-<run_id>.zip`) containing `run.json`, `summary.md`, JSON Schema, and all cell evidence.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add `prune_run_artifacts` to `experiment/src/experiment/adapters/github_workflow.py` with unit tests mocking pagination and delete calls.
2. Update `.github/workflows/experiment.yml` to pack `experiment-run-<run_id>.zip`, render `$GITHUB_STEP_SUMMARY`, upload the single bundle, and prune intermediates on upload success.
3. Validate with `pixi run tools run check` and `pixi run tools run actions`, merge to `main`, and verify with live `smoke` and `pilot` dispatches.
<!-- SECTION:PLAN:END -->
