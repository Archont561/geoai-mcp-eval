---
id: GEO-024
title: Migrate remaining dataclasses and DTOs to Pydantic v2 BaseModel
status: To Do
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - domain
  - pydantic
  - models
milestone: m-5
dependencies:
  - GEO-022
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Standardize structured data models, value objects, request/response DTOs, and configuration records across `experiment/src/experiment/` on Pydantic v2 `BaseModel`, eliminating the current split between 26 Pydantic models and 41 stdlib `@dataclass` definitions (plus ad-hoc `NamedTuple` records).

### Current state

- **Already `pydantic.BaseModel` (`26` models):**
  - `domain/backend.py` (`BackendProfile`, `BackendsFile`)
  - `domain/task.py` (`DifficultyRubric`, `Provenance`, `Fixtures`, `HumanBaseline`, `Oracle`, `BudgetBounds`, `Task`)
  - `domain/run/{aggregate,measurement,provenance,trial}.py` (`ExperimentRun`, `InstrumentAudit`, `TokenUsage`, `AssertionResult`, `DeterminismAudit`, `OutcomeMetrics`, `CostAndProcessMetrics`, `BehavioralAnnotations`, `TrialMeasurement`, `EnvironmentPin`, `ModelPin`, `RunProvenance`, `Treatment`, `TrialKey`, `ArtifactRef`, `TranscriptEntry`, `TrialRecord`)
- **Still stdlib `@dataclass` / `NamedTuple` in `experiment/src/experiment/` (`41` dataclasses + `2` NamedTuples):**
  - `domain/`: `cache_key.py` (2), `jenks.py` (1), `prompts.py` (3), `task_validation.py` (2), `usage.py` (2), `run/measurement.py` (`RawTrialData`), `run/metrics.py` (`_TranscriptTally`)
  - `oracle/`: `_base.py` (3), `_evaluators.py` (1), `_gate.py` (1)
  - `services/`: `archive.py` (1), `backend_check.py` (2), `measurement.py` (1), `reports.py` (6), `run_spec.py` (1), `runs.py` (2), `workflow.py` (1 + `_Comparison`), `workflow_pilot.py` (1), `runners/ports.py` (3), `runners/ollama.py` (1), `runners/scripted.py` (1)
  - `adapters/`: `github_workflow.py` (1), `ollama.py` (2), `run_store.py` (1), `ssh_tunnel.py` (2), `subprocess_runner.py` (1)
  - `cli/`: `run.py` (3)
  - `analysis/`: `github_client.py` (1)

### Design rules & boundary constraints

1. **Consistent Pydantic v2 configuration:**
   - Immutable value objects & DTOs use `model_config = ConfigDict(frozen=True, extra="forbid")` (matching `domain/task.py` and `domain/run/`).
   - Mutable accumulators (such as `usage.py` cell token accumulators) use `ConfigDict(extra="forbid", validate_assignment=True)` or become immutable value transitions.
   - Replace hand-rolled `to_dict()` / `asdict()` / manual JSON serialization helpers with `model_dump(mode="json")` and `model_validate(...)` where applicable, preserving exact JSON wire schemas for reports, transcripts, manifests, and `--json` CLI output.

2. **Explicit scope boundary for non-serializable live handles and QGIS plugin:**
   - Live OS/runtime resource handles that wrap non-data objects (e.g., `OllamaProcess` holding `subprocess.Popen` + open file handle, or port/dependency injection containers holding live callables/protocols such as `RunDependencies` / `CellExecutionPorts`) either remain thin runtime wrapper classes or explicitly document `ConfigDict(arbitrary_types_allowed=True)` — never forcing OS handles through JSON serialization.
   - `experiment-qgis-plugin/experiment_plugin/` runs inside system QGIS's bundled Python environment (which does not guarantee `pydantic` is installed); keep `experiment_plugin/` stdlib-only unless a separate decision bundles dependencies with the plugin.

3. **Preserve Clean Architecture purity:**
   - `experiment.domain` remains 100% pure (zero `pathlib`, `os`, `tomllib`, or I/O imports); domain `BaseModel` fields use pure primitive/typed types only.
   - All `import-linter` contracts and `clean_code` (`rude`) rules continue to pass with `0` violations.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 All data value objects, domain models, and internal DTOs in `experiment/src/experiment/domain/` (`cache_key.py`, `jenks.py`, `prompts.py`, `task_validation.py`, `usage.py`, `run/measurement.py`, `run/metrics.py`) are migrated from `@dataclass` / `NamedTuple` to `pydantic.BaseModel` with explicit `ConfigDict` and field constraints.
- [ ] #2 All value/DTO models in `experiment/src/experiment/oracle/`, `services/`, `adapters/`, `cli/`, and `analysis/` (reports, run specs, backend-check config/results, archive/workflow summaries, SSH target/tunnel specs, retry policy, command result, CLI option bundles, GitHub client records) are migrated to `pydantic.BaseModel` (with explicit documented exclusion only for live OS process/file handles or protocol dependency containers).
- [ ] #3 Manual `dataclasses.asdict()` / custom `.to_dict()` serialization boilerplate is replaced with Pydantic `model_dump(mode="json")` / `model_validate(...)`, with zero regressions in existing JSON/CSV/CLI `--json` output contracts.
- [ ] #4 `experiment.domain` remains 100% pure (no `pathlib`, `os`, or I/O imports added during migration), and `experiment-qgis-plugin/` remains compatible with QGIS's stdlib runtime.
- [ ] #5 Unit tests verify validation errors (invalid types, out-of-range bounds, forbidden extra fields) and JSON round-tripping for the migrated Pydantic models.
- [ ] #6 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Audit & classify all 41 dataclasses + 2 NamedTuples:** Separate pure data/DTO models (migrate to `BaseModel` with `frozen=True, extra="forbid"`) from live resource handles (`OllamaProcess`) and port-injection containers (keep as plain runtime classes or `arbitrary_types_allowed=True`).
2. **Migrate `domain/` and `oracle/` first:** Convert `cache_key.py`, `jenks.py`, `prompts.py`, `task_validation.py`, `usage.py`, `run/measurement.py` (`RawTrialData`), `run/metrics.py`, and `oracle/{_base,_evaluators,_gate}.py`; replace `dataclasses.replace` calls with `model_copy(update=...)`.
3. **Migrate `adapters/`, `services/`, `cli/`, and `analysis/`:** Convert `adapters/{github_workflow,ollama,run_store,ssh_tunnel,subprocess_runner}.py`, `services/{archive,backend_check,measurement,reports,run_spec,runs,workflow,workflow_pilot,runners/*}.py`, `cli/run.py`, and `analysis/github_client.py`; remove redundant `asdict()` / `to_dict()` boilerplate in favor of `model_dump(mode="json")`.
4. **Update & expand tests:** Update tests expecting `dataclasses.FrozenInstanceError` to `pydantic.ValidationError` where applicable, add validation/round-trip tests for newly constrained models, and verify all CLI `--json` and report outputs remain schema-compatible.
5. **Run full verification gates:** Confirm `pixi run tools run fmt`, `check`, `md`, and `links` pass with `0` violations and `>=90%` coverage.
<!-- SECTION:PLAN:END -->
