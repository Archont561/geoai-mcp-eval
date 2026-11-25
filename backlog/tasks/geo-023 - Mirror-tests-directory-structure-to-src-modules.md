---
id: GEO-023
title: Mirror tests directory structure to src modules (1:1 module-to-test mapping)
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - testing
  - structure
  - ergonomics
milestone: m-5
dependencies:
  - GEO-022
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reorganize `experiment/tests/` and `experiment-qgis-plugin/tests/` so the test directory hierarchy mirrors the production source tree 1:1 — every non-dunder source module has a dedicated, predictably located test file at the mirrored path — and enforce the invariant automatically in CI so future modules cannot drift.

### Current state & gaps

1. **`experiment/` (`66` non-dunder source modules vs. `26` flat test files):**
   - `experiment/src/experiment/` is organized into Clean Architecture packages (`domain/`, `domain/run/`, `adapters/`, `adapters/mcp/`, `services/`, `services/runners/`, `cli/`, `oracle/`, `analysis/`, plus top-level `gis_ops.py`), whereas `experiment/tests/` is still a flat directory of 26 catch-all files (`test_adapters_core.py`, `test_domain_run.py`, `test_domain_validation_and_reports.py`, `test_sdk_transport_adapters.py`, `test_cli_ergonomics_and_layout.py`, `test_oracle.py`, `test_analyze.py`, etc.).
   - Finding the unit tests for a given module (or spotting which module lacks direct unit tests) requires grepping across flat files, and unrelated modules are coupled inside shared test modules.

2. **`experiment-qgis-plugin/` (`14` non-dunder source modules vs. `7` flat test files):**
   - `experiment-qgis-plugin/experiment_plugin/` has 14 modules (`_io.py`, `_processing_log.py`, `_review_cli.py`, `_review_merge.py`, `_session_io.py`, `_state.py`, `_tasks.py`, `_versions.py`, `host_observation.py`, `metrics.py`, `panel.py`, `plugin.py`, `review.py`, `session.py`), while `experiment-qgis-plugin/tests/` groups most internals into `test_plugin_internals.py`, `test_plugin_lifecycle.py`, and `test_plugin.py`.

### Target 1:1 mirroring convention

- **Canonical mapping rule:** Every non-dunder source file `<src_root>/<rel_dir>/<stem>.py` (excluding `__init__.py` and `__main__.py`) maps to `<tests_root>/<rel_dir>/test_<stem>.py`.
  - Leading-underscore private modules keep their underscore (`_ollama_chat.py` -> `test__ollama_chat.py`, `domain/run/_common.py` -> `domain/run/test__common.py`, `experiment_plugin/_io.py` -> `test__io.py`) so the mapping is mechanically 1-to-1 reversible with zero name collisions.
  - Examples under `experiment/tests/`:
    - `experiment/src/experiment/gis_ops.py` -> `experiment/tests/test_gis_ops.py`
    - `experiment/src/experiment/domain/backend.py` -> `experiment/tests/domain/test_backend.py`
    - `experiment/src/experiment/domain/run/measurement.py` -> `experiment/tests/domain/run/test_measurement.py`
    - `experiment/src/experiment/adapters/ssh_tunnel.py` -> `experiment/tests/adapters/test_ssh_tunnel.py`
    - `experiment/src/experiment/adapters/mcp/client.py` -> `experiment/tests/adapters/mcp/test_client.py`
    - `experiment/src/experiment/services/runners/ollama.py` -> `experiment/tests/services/runners/test_ollama.py`
    - `experiment/src/experiment/cli/archive.py` -> `experiment/tests/cli/test_archive.py`
    - `experiment/src/experiment/oracle/_evaluators.py` -> `experiment/tests/oracle/test__evaluators.py`
    - `experiment/src/experiment/analysis/dataset.py` -> `experiment/tests/analysis/test_dataset.py`
  - Examples under `experiment-qgis-plugin/tests/`:
    - `experiment-qgis-plugin/experiment_plugin/metrics.py` -> `experiment-qgis-plugin/tests/test_metrics.py`
    - `experiment-qgis-plugin/experiment_plugin/_processing_log.py` -> `experiment-qgis-plugin/tests/test__processing_log.py`

- **Cross-cutting, BDD, and repo-level tests:**
  - Keep `.alint.yml`-required anchors in place (`experiment/tests/test_smoke.py`, `experiment-qgis-plugin/tests/test_plugin.py`, `experiment-qgis-plugin/tests/test_plugin_scenarios.py`).
  - Keep cross-cutting / end-to-end / BDD / property / gate suites clearly separated from 1:1 module unit tests (e.g., top-level `test_cli_scenarios.py`, `test_architecture.py`, `test_clean_code_gate.py`, `test_properties.py`, `test_review_scenarios.py`, or a dedicated `integration/` subfolder where not pinned by `.alint.yml`).

- **Pytest collection & coverage compatibility:**
  - Configure `pytest` with `--import-mode=importlib` (or equivalent non-colliding package setup) in `pyproject.toml` so identically named mirrored test modules across different layers (e.g., `tests/cli/test_archive.py` vs. `tests/services/test_archive.py`, `tests/cli/test_tasks.py` vs. `tests/services/test_tasks.py`, `tests/adapters/test_ollama.py` vs. `tests/services/runners/test_ollama.py`) never trigger `ImportPathMismatchError`.
  - Ensure shared test helpers (`cli_harness.py`, `plugin_harness.py`) and root `conftest.py` fixtures remain cleanly importable from nested test subdirectories, and verify `[tool.coverage.run]` `omit` excludes all nested test files (`experiment/tests/**`).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every non-dunder Python source module under `experiment/src/experiment/` (all `domain/`, `domain/run/`, `adapters/`, `adapters/mcp/`, `services/`, `services/runners/`, `cli/`, `oracle/`, `analysis/`, and top-level modules) has a mirrored test module at `experiment/tests/<rel_dir>/test_<stem>.py` containing direct unit tests for that module.
- [ ] #2 Every non-dunder Python source module under `experiment-qgis-plugin/experiment_plugin/` has a mirrored test module at `experiment-qgis-plugin/tests/test_<stem>.py` containing direct unit tests for that module.
- [ ] #3 Existing catch-all unit test files are cleanly split into their mirrored per-module test files without losing test assertions, while BDD scenario tests (`test_cli_scenarios.py`, `test_plugin_scenarios.py`, `test_review_scenarios.py`), repo gates (`test_architecture.py`, `test_clean_code_gate.py`), property tests (`test_properties.py`), and `.alint.yml`-required anchors (`test_smoke.py`, `test_plugin.py`) remain intact and cleanly separated.
- [ ] #4 `pyproject.toml` pytest and coverage configuration handles nested same-basename test modules without import collisions (`--import-mode=importlib` or package-qualified layout) and preserves shared `conftest.py` / `cli_harness.py` / `plugin_harness.py` resolution.
- [ ] #5 An automated structural test (in `experiment/tests/test_architecture.py` or a dedicated check wired into `pixi run tools run check`) enforces the 1:1 `src` -> `tests` mirror invariant across both `experiment` and `experiment-qgis-plugin`, failing if any non-dunder source module lacks its mirrored test file.
- [ ] #6 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, `97/97` (or updated) `alint` rules passing, and `>=90%` test coverage with zero dropped test cases.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Configure pytest & enforcement first:** Enable `--import-mode=importlib` and recursive test `omit` in `pyproject.toml`, verify `cli_harness` / `plugin_harness` importability from nested subdirectories, and add the automated `src` -> `tests` 1:1 mirror check (initially listing all missing mirrored test files as the concrete worklist).
2. **Mirror `experiment/src/experiment/domain/` and `oracle/` and `analysis/`:** Split `test_domain_run.py`, `test_domain_validation_and_reports.py`, `test_usage.py`, `test_cache.py`, `test_oracle.py`, and `test_analyze.py` into `tests/domain/`, `tests/domain/run/`, `tests/oracle/`, and `tests/analysis/` per-module files; add direct tests for any thin/helper modules (`_common.py`, `_base.py`, `_jenks.py`, `prompts.py`, etc.).
3. **Mirror `experiment/src/experiment/adapters/`:** Split `test_adapters_core.py`, `test_backends.py`, `test_sdk_transport_adapters.py`, `test_run_archive.py`, `test_task_repository.py`, `test_task_suite.py`, `test_github_workflow_adapter.py`, `test_mcp_client.py`, and `test_harness_ports.py` into `tests/adapters/` and `tests/adapters/mcp/` per-module files.
4. **Mirror `experiment/src/experiment/services/` and `cli/`:** Split `test_backend_check.py`, `test_measurement_service.py`, `test_qgis_service.py`, `test_prototype.py`, `test_workflow_cli.py`, and `test_cli_ergonomics_and_layout.py` into `tests/services/`, `tests/services/runners/`, and `tests/cli/` per-module files.
5. **Mirror `experiment-qgis-plugin/experiment_plugin/`:** Split `test_plugin_internals.py`, `test_plugin_lifecycle.py`, `test_review.py`, and `test_session.py` into per-module `experiment-qgis-plugin/tests/test_<stem>.py` files while keeping `test_plugin.py`, `test_plugin_scenarios.py`, and `test_review_scenarios.py` compliant with `.alint.yml`.
6. **Verify all gates:** Run `pixi run tools run fmt`, `check`, `md`, and `links`; confirm the 1:1 mirror invariant test passes with zero exceptions, coverage stays `>=90%`, and all `alint` / `import-linter` / `clean_code` checks pass.
<!-- SECTION:PLAN:END -->
