---
id: GEO-026
title: Refactor string-based sets and exit codes into typed StrEnum and IntEnum classes with domain methods
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - architecture
  - domain
  - enums
  - typing
milestone: m-5
dependencies:
  - GEO-024
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace ad-hoc string sets (`frozenset` / `tuple` of magic strings), `Literal[...]` type aliases, parallel lookup dictionaries, and bare integer exit/status constants across `experiment/src/experiment/` (and stdlib-compatible parts of `experiment-qgis-plugin/experiment_plugin/`) with first-class Python 3.13 `enum.StrEnum` and `enum.IntEnum` classes carrying cohesive, typed domain methods.

### Current state & inventory

Stringly-typed vocabularies and parallel lookup tables are currently scattered across layers:

1. **Run ontology (`experiment/src/experiment/domain/run/_common.py`, `measurement.py`, `trial.py`):**
   - Eight `Literal[...]` aliases (`RunStage`, `Paradigm`, `EnforcementLevel`, `ExecutionStatus`, `AssertionTier`, `ArtifactKind`, `TrajectoryClass`, `FailureClass`).
   - Parallel module-level lookup dicts and sets: `_ARM_TO_PARADIGM`, `_ENFORCE_TO_LEVEL`, `ENFORCEMENT_LEVELS`, `_ENFORCEMENT_BY_NAME`, `_EXECUTION_STATUS_BY_NAME`, `_TIER_ALIASES`, `_TYPE_TO_TIER`, `_UNENFORCED_PARADIGMS`.
   - Separate free functions (`arm_to_paradigm`, `enforce_code_to_level`, `parse_enforcement_level`, `parse_execution_status`, `infer_assertion_tier`) operating on raw `str` values instead of enum methods.

2. **Task & oracle ontology (`experiment/src/experiment/domain/task.py`, `domain/task_validation.py`, `gis_ops.py`):**
   - `Literal[...]` aliases: `TaskFamily`, `Expressibility`, `Contamination`, `BaselineStatus`.
   - String sets & dicts: `SUPPORTED_ORACLE_TYPES`, `REQUIRED_PILOT_TRAPS`, `REQUIRED_TASK_FAMILIES`, `SUPPORTED_DE9IM_RELATIONS`, `ORACLE_ASSERTION_FIELDS`, `_DE9IM_MATRIX_OVERRIDES`.

3. **Execution, adapters, CLI, and analysis (`adapters/`, `services/`, `cli/`, `analysis/`):**
   - Bare tuples/literals: `ARMS = ("A", "B")`, `DRIVERS = ("scripted", "ollama")`, CLI `Literal["A", "B"]`, `Literal["smoke", "pilot"]`, `Literal["N1", "N2", "N3", "N4"]`, `CachePolicy = Literal["use", "refresh"]`, `TunnelErrorKind = Literal["ssh-unreachable", "tunnel-dead"]`.
   - Bare integer constants & lookup maps:
     - `cli/env.py`: `EXIT_READY = 0`, `EXIT_SSH_UNREACHABLE = 10`, `EXIT_TUNNEL_DEAD = 11`, `EXIT_MODEL_ABSENT = 12`, `EXIT_AUTH_CLIENT = 13`, `EXIT_TOKEN_LIMIT = 14`, `EXIT_COMPLETION_REJECTED = 15`, plus `_BACKEND_CHECK_EXIT_CODES: dict[str, int]`.
     - `adapters/ollama.py`: `RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})`.
   - Artifact kind mapping in `adapters/_archive_artifacts.py`: `_EXACT_KINDS`, `_SUFFIX_KINDS`, `infer_artifact_kind()`.

4. **QGIS plugin (`experiment-qgis-plugin/experiment_plugin/`):**
   - Repeated raw status strings (`"not_started"`, `"in_progress"`, `"recorded"`, `"abandoned"`, `"pending_review"`, `"reviewed"`, `"session_manual"`, `"post_session_review"`, `"processing_log"`) that can safely adopt stdlib `StrEnum` (Python 3.11+ stdlib, zero external dependencies).

### Target enum design & typed methods

1. **`StrEnum` domain value types with behavior attached to the enum:**
   - `RunStage(StrEnum)`: `PREFLIGHT`, `SMOKE`, `PILOT`, `STUDY`.
   - `Arm(StrEnum)`: `A`, `B` with `@classmethod def expand(cls, raw: str) -> tuple[Arm, ...]` and `def to_paradigm(self) -> Paradigm`.
   - `Driver(StrEnum)`: `SCRIPTED`, `OLLAMA`.
   - `Paradigm(StrEnum)`: `TYPED_MCP`, `CODEGEN`, `HYBRID_MCP_CODE`, `CODE_DRIVING_MCP`, `HUMAN_GUI` with `@classmethod def from_arm(cls, arm: str | Arm) -> Paradigm` and `def allows_enforcement(self) -> bool`.
   - `EnforcementLevel(StrEnum)`: `NONE`, `DECLARATIVE`, `SYNTACTIC`, `SEMANTIC_REPAIR`, `TRANSACTIONAL` with `@classmethod def from_code(cls, code: str) -> EnforcementLevel`, `@classmethod def parse(cls, raw: str) -> EnforcementLevel`, and `def legacy_code(self) -> str`.
   - `ExecutionStatus(StrEnum)`: `OK`, `ABORTED`, `ERROR`, `SMOKE` with `@classmethod def parse(cls, raw: str | None, *, default: ExecutionStatus = ...) -> ExecutionStatus`.
   - `AssertionTier(StrEnum)`: `TRIVIAL`, `SPATIAL`, `VALUE` with `@classmethod def infer(cls, assertion_type: str, *, explicit_tier: str | None = None) -> AssertionTier | None`.
   - `ArtifactKind(StrEnum)`: `DELIVERABLE`, `TRANSCRIPT`, `LOG`, `ORACLE_PASSES`, `SCRIPT`, `OTHER` with `@classmethod def from_filename(cls, name: str) -> ArtifactKind`.
   - `TrajectoryClass(StrEnum)` and `FailureClass(StrEnum)`.
   - `TaskFamily(StrEnum)` (`P`, `A`, `C`) with `def display_name(self) -> str`, `Expressibility(StrEnum)`, `Contamination(StrEnum)`, `BaselineStatus(StrEnum)`.
   - `OracleAssertionType(StrEnum)` with `def required_fields(self) -> frozenset[str]` and `def default_tier(self) -> AssertionTier`.
   - `PilotTrap(StrEnum)` and `De9imRelation(StrEnum)` with `def matrix_override(self) -> str | None`.
   - `TunnelErrorKind(StrEnum)`, `BackendProbeErrorKind(StrEnum)` (with `def exit_code(self) -> BackendCheckExitCode`), and `CachePolicy(StrEnum)`.

2. **`IntEnum` numeric code types with typed methods:**
   - `BackendCheckExitCode(IntEnum)`: `READY = 0`, `SSH_UNREACHABLE = 10`, `TUNNEL_DEAD = 11`, `MODEL_ABSENT = 12`, `AUTH_CLIENT = 13`, `TOKEN_LIMIT = 14`, `COMPLETION_REJECTED = 15`, with `@classmethod def from_error_kind(cls, kind: BackendProbeErrorKind | str) -> BackendCheckExitCode`.
   - `RetryableHttpStatus(IntEnum)`: `TOO_MANY_REQUESTS = 429`, `INTERNAL_SERVER_ERROR = 500`, `BAD_GATEWAY = 502`, `SERVICE_UNAVAILABLE = 503`, `GATEWAY_TIMEOUT = 504`, with `@classmethod def contains(cls, status_code: int) -> bool`.

3. **Pydantic v2, JSON wire compatibility, and architecture constraints:**
   - Because `StrEnum` subclasses `str` and `IntEnum` subclasses `int`, Pydantic v2 `BaseModel` validation, JSON Schema generation, `model_dump(mode="json")`, Typer CLI options, and pandas DataFrame projections remain 100% wire-compatible with existing manifests, archives, and `schema-v1.json`.
   - `experiment.domain` stays 100% pure (stdlib `enum` only; zero I/O imports).
   - Keep backwards-compatible module re-exports or thin delegating aliases where public symbols are imported across tests/scripts, removing duplicated raw string sets and lookup tables.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 All `experiment/src/experiment/domain/run/` vocabularies (`RunStage`, `Paradigm`, `EnforcementLevel`, `ExecutionStatus`, `AssertionTier`, `ArtifactKind`, `TrajectoryClass`, `FailureClass`) are refactored from `Literal` + raw lookup dicts into `StrEnum` classes with typed parsing/classification methods.
- [x] #2 All task, oracle, and geometry vocabularies (`TaskFamily`, `Expressibility`, `Contamination`, `BaselineStatus`, `OracleAssertionType`, `PilotTrap`, `De9imRelation`) are refactored from `Literal` / `frozenset` constants into `StrEnum` classes with typed methods (`required_fields()`, `default_tier()`, `matrix_override()`, etc.).
- [x] #3 Execution, transport, CLI, and analysis vocabularies (`Arm`, `Driver`, `TunnelErrorKind`, `BackendProbeErrorKind`, `CachePolicy`) and integer code sets (`BackendCheckExitCode`, `RetryableHttpStatus`) are refactored into `StrEnum` and `IntEnum` classes with typed conversion/predicate methods, eliminating bare `EXIT_*` and `RETRYABLE_STATUSES` raw sets/maps.
- [x] #4 Repeated status string sets in `experiment-qgis-plugin/experiment_plugin/` (`MetricsStatus`, `SessionStatus`, `TrajectoryOrigin`) use stdlib `StrEnum` while preserving zero third-party dependencies for QGIS Python compatibility.
- [x] #5 Pydantic v2 serialization (`model_dump(mode="json")`), JSON Schema (`ExperimentRun.model_json_schema()` and `schema-v1.json`), Typer CLI flags, and pandas DataFrame column values remain 100% backward compatible, and `mypy` passes with zero errors across all strict enum-typed call sites.
- [x] #6 Hypothesis property tests verify enum exhaustion, case/code parsing round-trips, invalid value rejection, and `IntEnum` exit/status code mappings.
- [x] #7 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, `97/97` `alint` rules passing, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Refactor `domain/run/_common.py` and `domain/run/{measurement,trial,aggregate}.py`:** Replace the 8 `Literal` types and parallel lookup dicts with `StrEnum` classes and attach `from_arm`, `allows_enforcement`, `from_code`, `parse`, `legacy_code`, `infer`, and `from_filename` methods; keep thin delegating functions only where needed for backwards compatibility.
2. **Refactor `domain/task.py`, `domain/task_validation.py`, and `gis_ops.py`:** Replace `TaskFamily`, `Expressibility`, `Contamination`, `BaselineStatus`, `SUPPORTED_ORACLE_TYPES`, `REQUIRED_PILOT_TRAPS`, `REQUIRED_TASK_FAMILIES`, `SUPPORTED_DE9IM_RELATIONS`, `ORACLE_ASSERTION_FIELDS`, and `_DE9IM_MATRIX_OVERRIDES` with typed `StrEnum` classes and methods.
3. **Refactor adapters, services, CLI, and analysis enums (`StrEnum` + `IntEnum`):** Introduce `Arm`, `Driver`, `TunnelErrorKind`, `BackendProbeErrorKind`, `CachePolicy`, `BackendCheckExitCode(IntEnum)`, and `RetryableHttpStatus(IntEnum)` and wire them through `cli/{run,env,archive}.py`, `services/{run_spec,runs,backend_check,workflow_pilot}.py`, `adapters/{harness_io,ollama,backend_probe,ssh_tunnel,_archive_artifacts}.py`, and `analysis/github_client.py`.
4. **Refactor `experiment-qgis-plugin/` status strings to stdlib `StrEnum`:** Define `SessionStatus`, `MetricsStatus`, and `TrajectoryOrigin` in `experiment_plugin/` without adding any non-stdlib dependency.
5. **Update & expand Hypothesis property tests and run all gates:** Add enum exhaustion and parsing round-trip properties, then verify `pixi run tools run fmt`, `check`, `md`, and `links` pass cleanly.
<!-- SECTION:PLAN:END -->
