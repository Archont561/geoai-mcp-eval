---
id: m-5
title: "Ontology & Clean Architecture"
---

## Description

Architectural refactoring milestone: reorganize `experiment/` around the English
experiment ontology (`Task`, `Treatment`, `ExperimentRun`, `TrialRecord`,
`TrialMeasurement` DTO, `InstrumentAudit`), enforce exhaustive Clean Architecture
boundaries, unify run storage into one self-contained `.zip` archive with lazy
submodel hydration, refactor the CLI to meaningful task/run commands, consolidate
GitHub Actions runs into a single artifact, and move analysis into a GitHub-backed
Marimo data client.

Exit criteria:

- Pure English Pydantic v2 aggregate (`ExperimentRun` + `TrialMeasurement` DTO) owns all run data with zero Polish acronyms in code or schemas.
- `RunArchive` saves and loads one self-contained `experiment-run-<run_id>.zip` with lazy submodel hydration and SHA-256 member verification.
- Flat legacy top-level modules (`backends.py`, `drivers.py`, `harness.py`, `prototype.py`, `scripted.py`, `mcp_*.py`, `task_suite.py`) are migrated into strict `domain` / `adapters` / `services` / `cli` layers with exhaustive `import-linter` contracts and 0 `clean_code` violations.
- `experiment` CLI exposes meaningful task/run commands (`tasks ls|show|validate`, `run mcp|codegen|all|smoke`, `score`, `archive`, `env`) with analysis decoupled from the CLI.
- GitHub Actions `experiment.yml` ends each run with exactly one downloadable `.zip` artifact.
- Marimo analysis notebooks load runs via `experiment.analysis.GitHubRunClient` and produce typed pandas DataFrames without importing the LLM cache.
