---
id: GEO-025
title: Replace experiment/backends.toml with unified experiment.toml project configuration
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - config
  - pydantic
  - ergonomics
milestone: m-5
dependencies:
  - GEO-024
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace the single-purpose `experiment/backends.toml` file with a single, validated `experiment.toml` project configuration file at the repository root (or `experiment/experiment.toml`, located via a single path resolver) covering all project-wide experiment settings — backends, paths, runner defaults, budgets, caching, backend preflight / SSH tunnel settings, archive options, and QGIS/MCP defaults — backed by a pure Pydantic v2 `ExperimentConfig` model.

### Current state & motivation

Currently, project configuration is fragmented across four places:

1. **`experiment/backends.toml`** — holds only `[backends.<name>]` tables (`local`, `remote-ollama`, `free-open`).
2. **Hardcoded module constants** — e.g., `DEFAULT_MODEL = "qwen2.5-coder:0.5b"`, `DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"`, `DEFAULT_RETRY_BACKOFF_S`, poll timeouts (`30.0s`), smoke `max_tokens`, runner turn/script limits, and `results/` / `experiment/tasks/` paths in `adapters/paths.py`.
3. **Duplicated CLI option defaults** — `cli/run.py`, `cli/env.py`, and `cli/archive.py` each hardcode defaults (`--model qwen2.5:3b` vs. `qwen2.5-coder:0.5b`, `--enforce N3` vs. `semantic_repair`, `--repetitions 1` vs. `2`, `--arms A,B`, `--poll-timeout-s 30.0`, etc.).
4. **Ad-hoc environment variables** — `EXPERIMENT_*`, `OLLAMA_*`, `MODEL`, `RUN_ID` read independently in CLI options and adapters without a unified precedence contract.

Consolidating these into `experiment.toml` + a validated Pydantic `ExperimentConfig` eliminates default drift, documents all knobs in one version-controlled file, and makes experimental runs reproducible from one inspected config snapshot.

### Target `experiment.toml` schema & architecture

1. **Pure Pydantic v2 configuration schema (`experiment/src/experiment/domain/config.py`):**
   - Root `ExperimentConfig(BaseModel)` (`extra="forbid"`, `frozen=True`) composed of cohesive nested `BaseModel` sections:
     - `[experiment]` (`default_backend`, `default_driver`, `default_stage`, `default_arms`, `default_repetitions`, `default_enforce`, `use_llm_cache`)
     - `[paths]` (`tasks_dir`, `results_dir`, `cache_dir` — stored as relative/string paths in domain, resolved to `Path` inside `adapters/paths.py` so `experiment.domain` stays 100% pure with zero `pathlib`/`os`/`tomllib` imports)
     - `[runner]` (`max_turns`, `max_cell_tokens`, `script_timeout_s`, `mcp_timeout_s`)
     - `[backend_check]` (`poll_timeout_s`, `poll_interval_s`, `smoke_max_tokens`)
     - `[ssh]` (`remote_bind_host`, `remote_bind_port`, `local_bind_host`, `connect_timeout_s` — strictly non-secret topology defaults; never keys or passwords)
     - `[archive]` (`fail_on_missing`, `skip_oracle`, `keep_artifact`)
     - `[qgis]` (`timeout_s`, headless defaults)
     - `[backends.<name>]` (`dict[str, BackendProfile]`, preserving `local`, `remote-ollama`, `free-open`, with `api_key_env` references only and zero committed secrets)

2. **Adapter loader & precedence contract (`experiment/src/experiment/adapters/config.py` via `pydantic-settings`):**
   - Adopt **`pydantic-settings`** (`BaseSettings` + `TomlConfigSettingsSource` + `EnvSettingsSource`, nested delimiter `__`) inside `adapters/config.py` (declared in `pixi.toml` `[feature.experiment.pypi-dependencies]`) to load `experiment.toml` and `EXPERIMENT_*` environment variables without hand-rolled `tomllib` / `os.environ` merging boilerplate, while keeping `domain/config.py` pure Pydantic `BaseModel`.
   - Supports `--config <path>` / `EXPERIMENT_CONFIG` override and graceful fallback to validated defaults when running in isolated test fixtures.
   - Enforces a single, deterministic precedence order across every command:
     **CLI flags > `EXPERIMENT_*` environment variables > `experiment.toml` > `ExperimentConfig` model defaults**.
   - Exposes `experiment env config [--json]` (or similar inspection subcommand) so operators and CI logs can dump the effective resolved config (with secret values never included) for run provenance.

3. **Clean cutover from `experiment/backends.toml`:**
   - Migrate all profiles from `experiment/backends.toml` into `[backends.*]` in `experiment.toml`, update `adapters/paths.py`, `adapters/backends.py`, `services/{run_spec,backend_check,workflow,workflow_pilot}.py`, `cli/{run,env,archive,score,tasks}.py`, docs, and tests, and remove the obsolete `experiment/backends.toml`.
   - Add an `.alint.yml` rule verifying `experiment.toml` exists and passes schema validation.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A root `experiment.toml` file replaces `experiment/backends.toml` and defines typed sections for `[experiment]`, `[paths]`, `[runner]`, `[backend_check]`, `[ssh]`, `[archive]`, `[qgis]`, and `[backends.*]` (`local`, `remote-ollama`, `free-open`), containing zero secrets.
- [ ] #2 `experiment/src/experiment/domain/config.py` defines a pure Pydantic v2 `ExperimentConfig` (and nested section `BaseModel`s with `extra="forbid"`, `frozen=True`, and numeric/enum bounds) without importing `tomllib`, `os`, or `pathlib`.
- [ ] #3 `experiment/src/experiment/adapters/config.py` uses `pydantic-settings` (`TomlConfigSettingsSource` + `EnvSettingsSource`) to load `experiment.toml` (supporting `--config` / `EXPERIMENT_CONFIG`) and merge overrides under the documented precedence order: CLI flags > `EXPERIMENT_*` env vars > `experiment.toml` > model defaults.
- [ ] #4 `adapters/backends.py`, `adapters/paths.py`, `services/{run_spec,backend_check,workflow,workflow_pilot}.py`, and `cli/{run,env,archive,score,tasks}.py` consume resolved `ExperimentConfig` defaults instead of duplicated hardcoded constants, eliminating drift across subcommands.
- [ ] #5 Obsolete `experiment/backends.toml` and stale references in code, CLI help text, tests, and docs are removed/updated, and `.alint.yml` enforces the presence of `experiment.toml`.
- [ ] #6 Unit and CLI tests cover valid `experiment.toml` loading, unknown-key / invalid-value rejection (`extra="forbid"`), env-var and CLI-flag precedence, `--config` override, zero secret leakage in config inspection output, and fallback behavior when no config file exists.
- [ ] #7 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Design pure `ExperimentConfig` schema (`domain/config.py`):** Define `ExperimentConfig` and nested section models (`ExperimentDefaults`, `PathsConfig`, `RunnerConfig`, `BackendCheckConfig`, `SshDefaults`, `ArchiveConfig`, `QgisConfig`, reusing `BackendProfile` from `domain/backend.py`).
2. **Implement TOML + env config loader (`adapters/config.py` & `adapters/paths.py`):** Add `pydantic-settings` to `pixi.toml`, add `config_path(repo)` pointing to `experiment.toml`, implement `load_config(path=None, env=None)` via `BaseSettings` + `TomlConfigSettingsSource` + `EnvSettingsSource`, and wire `adapters/backends.py` to read `[backends.*]` through `load_config()`.
3. **Create `experiment.toml` and remove `experiment/backends.toml`:** Populate `experiment.toml` with the project's canonical defaults and backend profiles (`local`, `remote-ollama`, `free-open`), remove `experiment/backends.toml`, and add an `.alint.yml` presence rule for `experiment.toml`.
4. **Wire services & CLI:** Replace scattered hardcoded defaults in `services/{run_spec,backend_check,workflow,workflow_pilot}.py` and `cli/{run,env,archive,score,tasks}.py` with values sourced from `ExperimentConfig`, add `--config` / `EXPERIMENT_CONFIG` support, and expose config inspection (`--json`) with zero secret output.
5. **Update tests & docs and run full gates:** Migrate `backends.toml` test fixtures to `experiment.toml`, add comprehensive config validation & precedence tests, update docs/READMEs referencing `backends.toml`, and verify `pixi run tools run fmt`, `check`, `md`, and `links`.
<!-- SECTION:PLAN:END -->
