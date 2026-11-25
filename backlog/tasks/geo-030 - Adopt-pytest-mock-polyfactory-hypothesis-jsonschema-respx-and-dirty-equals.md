---
id: GEO-030
title: Adopt pytest-mock, polyfactory, hypothesis-jsonschema, respx, and dirty-equals in the test suite
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
updated_date: '2026-11-25T00:00:00Z'
labels:
  - testing
  - dependencies
  - hypothesis
  - bdd
  - fixtures
milestone: m-5
dependencies:
  - GEO-027
  - GEO-028
ordinal: 30000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Eliminate remaining test-fixture, mock-patching, JSON-schema strategy, HTTP-mocking, and partial-assertion boilerplate across `experiment/tests/` (and shared test tooling) by adopting five focused, pure-Python test libraries in `[feature.python.pypi-dependencies]`: **`pytest-mock`**, **`polyfactory`**, **`hypothesis-jsonschema`**, **`respx`**, and **`dirty-equals`**.

### Current boilerplate & target library replacements

1. **`pytest-mock` (`mocker` fixture) -> `experiment/tests/fakes.py` & BDD step bindings:**
   - Replace manual `monkeypatch.setattr(...)` + hand-wired `MagicMock` teardown plumbing with `mocker.patch(...)`, `mocker.MagicMock(...)`, and `mocker.create_autospec(...)` where pytest-managed lifecycle and call-spy ergonomics (`mocker.spy`) simplify fixtures and BDD steps.

2. **`polyfactory` (`ModelFactory`) -> `experiment/tests/fixtures.py`:**
   - `fixtures.py` manually constructs verbose baseline Pydantic v2 models (`ExperimentRun`, `TrialMeasurement`, `TrialRecord`, `Task`, `BackendProfile`, `CacheKeySpec`, `RunProvenance`).
   - Introduce typed `polyfactory.factories.pydantic_factory.ModelFactory` subclasses exposed via pytest fixtures so tests only specify fields relevant to the scenario or property under test.

3. **`hypothesis-jsonschema` (`from_schema`) -> schema fuzz testing:**
   - Automatically derive Hypothesis strategies directly from `schema-v1.json` and `ExperimentRun.model_json_schema()` via `hypothesis_jsonschema.from_schema(...)`, replacing hand-coded nested dict/JSON strategies and verifying that every schema-valid payload round-trips cleanly through Pydantic v2 models.

4. **`respx` -> declarative `httpx` mocking (pairs with `GEO-028` & `GEO-029`):**
   - Once generic HTTP calls (`adapters/backends.py`, `adapters/backend_probe.py`) and GitHub artifact downloads (`analysis/github_client.py`) run on `httpx`, use `respx` to mock HTTP routes, status codes (`429`/`503`/redirects), and JSON bodies declaratively in BDD steps (`backend-preflight.feature`, `analysis-dataset.feature`) instead of mocking private SDK/session internals.

5. **`dirty-equals` -> concise partial assertions:**
   - Replace verbose multi-line timestamp/UUID/regex unpacking assertions in provenance, archive, and manifest tests with `IsUUID`, `IsNow(iso_string=True)`, `IsPositiveFloat`, and `IsPartialDict`.

### Guardrails

- All five libraries belong strictly in `[feature.python.pypi-dependencies]` (dev/test only — zero impact on runtime `experiment` or `experiment-qgis-plugin/` dependencies).
- Keep `experiment/tests/conftest.py` and `experiment-qgis-plugin/tests/conftest.py` as thin re-export shims to avoid pytest basename collisions.
- Preserve Hypothesis-only unit tests and non-programmer BDD feature prose established in `GEO-027`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `pytest-mock`, `polyfactory`, `hypothesis-jsonschema`, `respx`, and `dirty-equals` are added to `[feature.python.pypi-dependencies]` in `pixi.toml` (not runtime dependencies) and `pixi.lock` is refreshed cleanly.
- [x] #2 `experiment/tests/fixtures.py` uses `polyfactory` `ModelFactory` fixtures for core Pydantic domain models (`Task`, `ExperimentRun`, `TrialMeasurement`, `BackendProfile`, etc.), reducing manual sample-construction boilerplate.
- [x] #3 `experiment/tests/fakes.py` and BDD step modules use `pytest-mock` (`mocker`) and `respx` (for `httpx`-backed backend preflight and GitHub artifact download routes) instead of manual session/response monkeypatching.
- [x] #4 Hypothesis schema tests use `hypothesis-jsonschema.from_schema(...)` against `schema-v1.json` and `ExperimentRun.model_json_schema()` to fuzz-test schema/model parity automatically.
- [x] #5 Provenance, manifest, and archive tests use `dirty-equals` matchers where appropriate to eliminate verbose timestamp/UUID/partial-dict boilerplate.
- [x] #6 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, `97/97` `alint` rules passing, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Add dev-only test dependencies:** Declare `pytest-mock`, `polyfactory`, `hypothesis-jsonschema`, `respx`, and `dirty-equals` under `[feature.python.pypi-dependencies]` in `pixi.toml` and update `pixi.lock`.
2. **Adopt `polyfactory` in `experiment/tests/fixtures.py`:** Define typed `ModelFactory` classes for core Pydantic models and expose them via clean pytest fixtures while keeping deterministic seeds for reproducible tests.
3. **Adopt `pytest-mock` and `respx` in `fakes.py` & BDD steps:** Replace manual `monkeypatch` + raw HTTP response mocks with `mocker` and `respx` route mocks across preflight, transport, and GitHub artifact download tests.
4. **Add `hypothesis-jsonschema` fuzz tests and `dirty-equals` matchers:** Fuzz-test `schema-v1.json` and `ExperimentRun.model_json_schema()` with `from_schema(...)` and simplify partial provenance/manifest assertions with `dirty-equals`.
5. **Run full verification gates:** Pass `pixi run tools run fmt`, `check`, `md`, and `links` with `>=90%` coverage and zero lint/architecture regressions.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Completed in Step 5 (`GEO-030`):

- **Dev-only test dependencies (`pixi.toml`)**: Added `pytest-mock`, `polyfactory`, `hypothesis-jsonschema`, `respx`, and `dirty-equals` strictly under `[feature.python.pypi-dependencies]` (zero impact on runtime `experiment`, `docs`, or `experiment-qgis-plugin/` dependencies).
- **`polyfactory` (`experiment/tests/fixtures.py` & `conftest.py`)**: Added deterministic seeded `ModelFactory` classes (`BackendProfileFactory`, `CacheKeySpecFactory`, `EnvironmentPinFactory`, `ModelPinFactory`, `RunProvenanceFactory`, `TrialKeyFactory`, `TreatmentFactory`, `TrialRecordFactory`, `ExperimentRunFactory`), wired baseline fixtures onto them, and exposed factory fixtures (`backend_profile_factory`, `run_provenance_factory`, `trial_record_factory`, `experiment_run_factory`) via pytest DI.
- **`pytest-mock` & `respx` (`fakes.py`, `test_backends.py`, `test_backend_probe.py`, `test_github_client.py`)**: Migrated shared fake fixtures in `fakes.py` to `mocker: MockerFixture` and added declarative `respx` route tests exercising real `httpx.Client` calls across `adapters/backends.py`, `adapters/backend_probe.py`, and `analysis/github_client.py` (including real `httpx` cross-host `Authorization` header stripping on 302 artifact redirects).
- **`hypothesis-jsonschema` (`test_task.py`, `test_aggregate.py`)**: Added `from_schema(schema-v1.json)` and `from_schema(ExperimentRun.model_json_schema())` Hypothesis fuzz tests proving schema/model parity and JSON round-tripping.
- **`dirty-equals` (`test_run_archive.py`, `test_provenance.py`, `test_aggregate.py`)**: Adopted `IsPartialDict`, `IsStr`, `IsPositiveInt`, and `IsDatetime(iso_string=True)` for concise partial assertions on archive manifests, schemas, artifacts, and provenance payloads.
<!-- SECTION:NOTES:END -->
