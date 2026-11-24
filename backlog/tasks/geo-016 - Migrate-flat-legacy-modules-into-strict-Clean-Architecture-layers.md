---
id: GEO-016
title: Migrate flat legacy modules into strict Clean Architecture layers
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - refactor
  - clean-code
milestone: m-5
dependencies:
  - GEO-014
  - GEO-015
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Eliminate the flat legacy modules sitting at the root of `experiment/src/experiment/` outside the four Clean Architecture layers (`domain/`, `adapters/`, `services/`, `cli/`) so the package layout is immediately readable and every module obeys explicit dependency direction:

- `backends.py` -> pure profile schemas in `domain/backend.py`, TOML loading + HTTP retry session in `adapters/llm_client.py`.
- `drivers.py` & `scripted.py` -> paradigm runners under `services/runners/` (`mcp_runner.py`, `codegen_runner.py`, `scripted_runner.py`) delegating HTTP, MCP, and sandbox execution to `adapters/`.
- `harness.py` & `prototype.py` -> remove `prototype.py` shim; move pure request/spec models to `domain/run/` and sandbox/transcript I/O to `adapters/`.
- `mcp_client.py` & `mcp_server.py` -> move under `adapters/mcp/`; keep the Arm A GIS operation catalogue (`gis_ops.py`) isolated from `oracle/`.
- `task_suite.py` -> split pure suite validation rules into `domain/suite_validation.py` and keep filesystem/YAML loading in `adapters/task_repository.py`.
- Tighten `[tool.importlinter]` contracts in `pyproject.toml` so layer enforcement is exhaustive across the entire `experiment` package with zero legacy exemptions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 No flat legacy orchestration/I/O modules (`backends.py`, `drivers.py`, `harness.py`, `prototype.py`, `scripted.py`, `mcp_client.py`, `mcp_server.py`, `task_suite.py`) remain outside `domain/`, `adapters/`, `services/`, `cli/`, `oracle/`, or `analysis/`.
- [x] #2 `[tool.importlinter]` contracts in `pyproject.toml` cover all package layers exhaustively and pass (`pixi run tools run architecture`).
- [x] #3 Arm A GIS tool catalogue (`gis_ops`) remains strictly forbidden from importing `oracle`.
- [x] #4 `pixi run tools run check` passes with 0 `clean_code` violations and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Move and split each legacy module one slice at a time, updating imports and tests per slice.
2. Expand `[tool.importlinter]` contracts in `pyproject.toml` and verify broken-import architecture tests still catch violations.
3. Run full `pixi run tools run check` after each slice.
<!-- SECTION:PLAN:END -->
