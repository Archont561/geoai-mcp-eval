---
id: GEO-018
title: Refactor experiment CLI to meaningful task and run commands
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - cli
  - refactor
milestone: m-5
dependencies:
  - GEO-015
  - GEO-016
  - GEO-017
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Refactor the `experiment` CLI so it focuses strictly on managing benchmark tasks, executing trials, scoring, archiving runs, and checking runtime environments — retiring the historical `proto` / `pilot` / `workflow` / `hello` split and removing analysis commands from the CLI (analysis moves to Marimo notebooks in `GEO-020`).

Target command tree:

- `experiment tasks`: `ls` (Rich/plain table of id, family, tier, expressibility, contamination, assertions, traps), `show <task_id>`, `validate`.
- `experiment run`: paradigm-specific subcommands so each arm exposes only valid options:
  - `experiment run mcp` (typed MCP paradigm; owns `--enforce`)
  - `experiment run codegen` (free Python/PyQGIS paradigm; enforcement fixed to `none`)
  - `experiment run all` (full paradigm matrix across tasks and repetitions -> single `ExperimentRun` archive)
  - `experiment run smoke` (fast non-agent plumbing probe replacing `hello`)
- `experiment score`: `eval <run_zip_or_dir>`, `determinism <task_id>`, `show <run_zip_or_dir>`.
- `experiment archive`: `pack`, `summary`, `inspect <run.zip>`, `prune-ci`.
- `experiment env`: `preflight`, `model`, `backend-check`, `mcp-ops`, `mcp-selftest`, `qgis {check, run}`.

Update `experiment/pyproject.toml` Tasknest manifest tasks, `.alint.yml`, `.github/workflows/ci.yml`, and BDD feature specs in `experiment/features/` to match the new command surface.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `experiment tasks ls`, `experiment tasks show <task_id>`, and `experiment tasks validate` work cleanly against `experiment/tasks/`.
- [ ] #2 `experiment run` exposes paradigm-specific subcommands (`mcp`, `codegen`, `all`, `smoke`) writing unified `ExperimentRun` / `RunArchive` outputs (local and CI share one layout).
- [ ] #3 `experiment score`, `experiment archive`, and `experiment env` cover scoring, determinism gate, zip packing/summary/inspection, and environment/sandbox probes; legacy `proto`, `pilot`, `workflow`, `hello`, and `analyze` CLI groups are removed.
- [ ] #4 `experiment/pyproject.toml` Tasknest tasks, `.alint.yml` (`ci-validates-pilot-task-suite` updated), `.github/workflows/ci.yml`, and all `experiment/features/*.feature` BDD specs are updated and green.
- [ ] #5 `pixi run tools run check` passes (`alint`, `lint`, `clean_code`, `architecture`, `test`, `md`).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Implement the new Typer modules (`cli/tasks.py`, `cli/run.py`, `cli/score.py`, `cli/archive.py`, `cli/env.py`) delegating strictly to `services/`.
2. Update `experiment/pyproject.toml` Tasknest tasks, `.alint.yml`, and `.github/workflows/ci.yml`.
3. Update BDD feature files (`experiment/features/*.feature`) and pytest-bdd bindings, then remove retired legacy CLI modules.
4. Verify full `pixi run tools run check` and `pixi run tools run actions`.
<!-- SECTION:PLAN:END -->
