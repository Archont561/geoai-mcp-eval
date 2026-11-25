---
id: GEO-021
title: Harden Clean Architecture boundaries, Clean Code split, and CLI ergonomics
status: In Progress
assignee: []
created_date: '2026-11-25T00:00:00Z'
labels:
  - architecture
  - clean-code
  - ergonomics
  - refactor
milestone: m-5
dependencies:
  - GEO-016
  - GEO-018
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Follow-up architectural and ergonomics hardening from the post-`m-5` Clean Architecture and Clean Code audit. While `experiment/domain/` is pure and `experiment/services/runners/ports.py` models the LLM harness via `Protocol` ports, several layer leaks, near-limit modules, and CLI/layout inconsistencies remain:

1. **Clean Architecture boundary leaks:**
   - `services/backend_check.py` (394 lines) smuggles a live `requests.Session` past `import-linter` via `adapters/ollama.py:create_session()`, builds raw `ssh` commands, inspects HTTP payloads (`resp.status_code`, `resp.json()`), and owns CLI exit codes (`EXIT_*`).
   - `services/workflow.py:54` spawns a subprocess invoking its own CLI (`python -m experiment tasks validate`) instead of calling `services.tasks.validate_suite()` directly, and its module docstring still references removed `experiment workflow ...` commands.
   - `adapters/task_suite.py` (383 lines) holds domain validation rules (`REQUIRED_PILOT_TRAPS`, `SUPPORTED_ORACLE_TYPES`, `ORACLE_ASSERTION_FIELDS`, `ValidationIssue`, `ValidationReport`) separately from `oracle/_evaluators.py`.
   - Six services (`qgis.py`, `backend_check.py`, `workflow.py`, `archive.py`, `measurement.py`, `scoring.py`) read `os.environ` or call `Path.exists()`/`is_file()`/`is_dir()` directly despite the adapter-only I/O contract.
   - `cli/env.py` imports `experiment.gis_ops` directly instead of going through `services/`, and `experiment-qgis-plugin/experiment_plugin/` has no `import-linter` contract protecting its Qt-free core (`session.py`, `review.py`, `metrics.py`).

2. **Clean Code split and deduplication:**
   - Modules hugging the 400-line `CC001` ceiling (`experiment_plugin/session.py` 398, `services/backend_check.py` 394, `experiment_plugin/review.py` 393, `adapters/task_suite.py` 383, `services/runs.py` 372, `adapters/run_archive.py` 358, `services/workflow.py` 349, `services/archive.py` 345) rely on 14–20 private helpers each and should split along responsibility boundaries.
   - Enforcement-level parsing is duplicated in `services/runs.py` and `services/archive.py` (both requiring `# type: ignore[return-value]`); move `ENFORCEMENT_LEVELS` and `parse_enforcement_level()` into `domain/run/_common.py`.
   - Service boundaries (`services/runs.py`, `services/scoring.py`, `services/archive.py`, `services/workflow_summary.py`) exchange untyped `dict[str, Any]` payloads (requiring `# type: ignore[arg-type]` casts); replace with typed frozen dataclasses (`RunSummary`, `CellSummary`, `ArchiveOverview`, `CompletenessReport`).
   - Unify or document the dual retry paths in `adapters/ollama.py` (`build_retry_session` vs `request_with_retry`), and add a parity test linking `services/qgis.py` and standalone `experiment_plugin/_versions.py`.
   - Replace multi-argument `parse_run_spec` and `TrialMeasurement.build` signatures (`# noqa: CC102`) with parameter dataclasses.

3. **CLI and run-layout ergonomics:**
   - Converge local (`<task>/arm_<A|B>/`, repetition fixed to `1`) and CI (`cell-<arm>-<task>-r<rep>/`) layouts onto one canonical `CellLayout` helper in `adapters/run_store.py` so local runs support repetitions and `services/archive.py` / `services/scoring.py` drop dual-layout sniffing.
   - Align CLI flags and environment variables across `run mcp|codegen|all`, `run cell`, and `env` (`EXPERIMENT_*` env vars with legacy `MODEL`/`RUN_ID` fallbacks, consistent `--cache/--no-cache` semantics, and `--json` support on Rich-only inspection commands).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `adapters/ollama.py:create_session()` is removed; SSH tunnel checks (`adapters/ssh_tunnel.py`) and HTTP model/completion probes live in `adapters/` behind typed `Protocol` ports consumed by `services/backend_check.py`, and CLI exit codes live in `cli/env.py`.
- [x] #2 `services/workflow.py` calls `services.tasks.validate_suite()` directly (no self-invoking `python -m experiment` subprocess) and updates stale `experiment workflow` docstrings.
- [x] #3 Pure task-suite semantic validation rules (`REQUIRED_PILOT_TRAPS`, oracle assertion types, `ValidationIssue`, `ValidationReport`) live in `domain/task_validation.py`, and `ENFORCEMENT_LEVELS` / `parse_enforcement_level()` live in `domain/run/_common.py` with zero duplicated parsers.
- [x] #4 Typed frozen DTOs replace untyped `dict[str, Any]` handoffs across `services/{runs,scoring,archive,workflow_summary}.py` and remove all `# type: ignore` suppressions in `experiment/src/experiment/services/`.
- [x] #5 `[tool.importlinter]` contracts in `pyproject.toml` forbid `cli -> gis_ops`, forbid direct `qgis`/`PyQt` imports in `experiment_plugin.{metrics,review,session}`, and keep `services/` free of direct `os.environ` / filesystem probes (PyQGIS version probing moved to an adapter).
- [x] #6 Every module currently above 340 lines (`backend_check.py`, `task_suite.py`, `runs.py`, `run_archive.py`, `workflow.py`, `archive.py`, `experiment_plugin/session.py`, `experiment_plugin/review.py`) is split by cohesion to comfortable headroom below `CC001`.
- [ ] #7 Local and CI cell runs share one canonical `cell-<arm>-<task>-r<rep>/` layout, CLI flags/env vars are aligned (`--cache/--no-cache`, `EXPERIMENT_*` env vars, `--json` on inspection commands), and `pixi run tools run check` passes with 0 `clean_code` violations and `>=90%` coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Slice 1 (Transport & workflow boundary cleanup):** Extract SSH and HTTP preflight probes into `adapters/` behind `Protocol` ports, remove `ollama.create_session()`, move exit-code mapping to `cli/env.py`, and replace the `tasks validate` subprocess in `services/workflow.py` with an in-process call to `services.tasks.validate_suite()`.
2. **Slice 2 (Domain consolidation & typed service DTOs):** Move `parse_enforcement_level()` to `domain/run/_common.py`, extract `domain/task_validation.py` from `adapters/task_suite.py`, introduce typed summary/overview DTOs in `services/`, and replace `parse_run_spec` / `TrialMeasurement.build` `# noqa: CC102` signatures with parameter objects.
3. **Slice 3 (Contract & plugin hardening):** Move PyQGIS host probing into `adapters/qgis_env.py`, route `cli/env.py:mcp_ops` through `services/`, split `experiment_plugin/{session,review}.py` cleanly, add `import-linter` contracts for `experiment_plugin` and `cli -> gis_ops`, and add a version-prober parity test.
4. **Slice 4 (CLI & cell-layout ergonomics):** Unify local and CI cell directories on `cell-<arm>-<task>-r<rep>/` via `adapters/run_store.py`, standardize `--cache/--no-cache` and `EXPERIMENT_*` env vars (preserving CI fallbacks), add `--json` to Rich-only inspection commands, and verify full `pixi run tools run check`, `md`, and `links`.
<!-- SECTION:PLAN:END -->
