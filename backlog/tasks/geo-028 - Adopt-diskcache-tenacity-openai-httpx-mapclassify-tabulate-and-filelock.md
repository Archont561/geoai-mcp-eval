---
id: GEO-028
title: Adopt diskcache, tenacity, openai/httpx, mapclassify, tabulate, and filelock to eliminate runtime boilerplate
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
updated_date: '2026-11-25T00:00:00Z'
labels:
  - architecture
  - dependencies
  - refactor
  - adapters
milestone: m-5
dependencies:
  - GEO-022
  - GEO-024
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace hand-rolled infrastructure, HTTP transport, retry/polling, caching, table-rendering, and numerical classification boilerplate in `experiment/src/experiment/` with mature, Python 3.13-compatible PyPI/conda libraries (several already present in the Pixi environment), while dropping redundant `requests` + `urllib3` dependencies and preserving strict Clean Architecture layer boundaries and stdlib-only QGIS plugin compatibility.

### Current boilerplate & target library replacements

1. **`diskcache` (already in `pixi.toml` `[feature.docs]`) -> `experiment/src/experiment/adapters/llm_cache.py`:**
   - Currently `llm_cache.py` (~85 LOC) hand-rolls `sqlite3` connections, WAL pragmas, schema initialization, and `INSERT OR REPLACE` SQL despite `GEO-009` targeting `diskcache`.
   - Promote `diskcache` into `[feature.experiment.pypi-dependencies]` and back `CompletionCache` with `diskcache.Cache(str(cache_dir))` while preserving `get()`, `put()` (still rejecting non-cacheable error payloads via `is_cacheable_response`), `count()`, and provenance isolation (never read by `analysis`).

2. **`tenacity` -> `adapters/ollama.py`, `adapters/openrouter.py`, `services/backend_check.py`:**
   - Replace custom retry/exponential-backoff loops (`request_with_retry`, `wait_ready`) and deadline polling loops (`_poll_model_digest` in `services/backend_check.py`) with declarative `tenacity.Retrying(stop=..., wait=..., retry=..., sleep=...)`, keeping `sleep` injectable for deterministic, zero-delay tests.

3. **`openai` SDK + `httpx` (already installed via `ollama` / `openrouter` / `mcp`) -> drop `requests` & `urllib3`:**
   - Generic OpenAI-compatible HTTP calls in `adapters/backends.py`, `adapters/ollama.py` (`build_retry_session`), and `adapters/backend_probe.py` still pull in `requests` + `urllib3` alongside `httpx`.
   - Adopt the official `openai` Python SDK (built on `httpx`, configured with custom `base_url`) for generic OpenAI-compatible endpoints (and `httpx.Client` where thin raw probing is needed), then remove `requests` and `urllib3` from `pixi.toml`.

4. **`mapclassify` (already installed in `default` via `geopandas`) -> Fisher–Jenks breaks:**
   - `domain/jenks.py` (~100 LOC) hand-rolls $O(k n^2)$ Fisher–Jenks dynamic programming while `mapclassify` (`mapclassify.FisherJenks`) is already installed in the default environment.
   - Delegate Fisher–Jenks computation to `mapclassify.FisherJenks` (or `jenkspy` where compiled wheels match all platforms) behind an adapter/oracle boundary so `experiment.domain` stays 100% pure Python (zero `numpy`/`geopandas` imports in `experiment.domain`), verified against existing `EXPECTED_JENKS_BREAKS` and Hypothesis monotonicity/optimality tests.

5. **Unify task schema generation on Pydantic v2 (`domain/task.py` & `adapters/task_repository.py`):**
   - Eliminate duplicate schema maintenance between hand-edited `schema-v1.json` and `domain/task.py` Pydantic models by deriving/verifying `schema-v1.json` from `Task.model_json_schema()` and validating through Pydantic v2 (keeping `jsonschema` only where external Draft-2020-12 compatibility checks require it).

6. **`tabulate` & `filelock` -> report tables and concurrent filesystem safety:**
   - Replace hand-concatenated Markdown pipe tables in `services/workflow_summary.py` and `services/archive.py` with `tabulate(..., tablefmt="github")`.
   - Guard concurrent writes to shared cell/harvest/cache directories in `adapters/run_store.py` with `filelock.FileLock`.

### Architectural guardrails

- `experiment.domain` MUST remain pure Python + Pydantic (no `diskcache`, `tenacity`, `httpx`, `openai`, `mapclassify`, `filelock`, or `tabulate` imports inside `domain/`).
- `experiment-qgis-plugin/` MUST remain 100% Python stdlib (+ `qgis-sdk` / QGIS runtime) with zero new third-party dependencies.
- Update `pixi.toml`, `experiment/pyproject.toml`, and `pixi.lock` cleanly; keep all `import-linter` contracts passing.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `diskcache` is promoted to `[feature.experiment.pypi-dependencies]` and replaces hand-rolled `sqlite3` SQL/WAL plumbing in `experiment/src/experiment/adapters/llm_cache.py` while keeping `is_cacheable_response` gating and cache API compatibility.
- [x] #2 `tenacity` replaces hand-rolled retry/backoff/polling loops in `adapters/ollama.py`, `adapters/openrouter.py`, and `services/backend_check.py`, preserving injectable `sleep` for fast deterministic tests.
- [x] #3 Generic OpenAI-compatible HTTP transport uses `openai` SDK / `httpx` (already installed), and `requests` + `urllib3` are removed from `pixi.toml` and `experiment/src/experiment/`.
- [x] #4 Fisher–Jenks breaks delegate to `mapclassify.FisherJenks` behind an adapter/oracle boundary (preserving pure `experiment.domain` import contracts) and produce identical breaks on all pilot tasks and Hypothesis property checks.
- [x] #5 Task schema validation eliminates drift between `schema-v1.json` and `Task` Pydantic v2 models (`Task.model_json_schema()` verified in tests).
- [x] #6 `tabulate` renders Markdown summary tables in `services/workflow_summary.py` / `services/archive.py`, and `filelock` protects concurrent shared-directory writes in `adapters/run_store.py`.
- [x] #7 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, `97/97` `alint` rules passing, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Update Pixi & package manifests:** Promote `diskcache` to `experiment`, add `tenacity`, `openai`, `tabulate`, and `filelock` to `pixi.toml` / `experiment/pyproject.toml`, remove `requests` and `urllib3`, and refresh `pixi.lock`.
2. **Migrate `llm_cache.py` to `diskcache`:** Swap raw `sqlite3` statements for `diskcache.Cache` with context-safe close handling and keep `is_cacheable_response` validation intact.
3. **Migrate HTTP transport and retry/polling loops:** Replace `requests.Session` + `urllib3.Retry` + `request_with_retry` + `wait_ready` + backend-check polling with `openai` / `httpx` + `tenacity.Retrying`.
4. **Adopt `mapclassify`, `tabulate`, `filelock`, and Pydantic schema generation:** Move Jenks computation behind an adapter/oracle helper backed by `mapclassify.FisherJenks`, render Markdown tables via `tabulate`, guard shared writes with `filelock`, and verify `schema-v1.json` parity with `Task.model_json_schema()`.
5. **Run full verification gates:** Update unit/BDD/fake mocks for `openai`/`httpx`/`diskcache`/`tenacity`, and pass `pixi run tools run fmt`, `check`, `md`, and `links`.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Completed in Step 3 (`GEO-028`):

- **`diskcache`** promoted to `[feature.experiment.pypi-dependencies]` and replaces raw `sqlite3` SQL/WAL boilerplate in `experiment/src/experiment/adapters/llm_cache.py`, preserving lazy DB creation, `is_cacheable_response` error-payload gating, `get()`/`put()`/`count()`, and analysis isolation.
- **`tenacity`** replaces hand-rolled retry, backoff, and polling loops across `adapters/ollama.py` (`request_with_retry`, `wait_ready`), `adapters/_ollama_chat.py`, `adapters/openrouter.py`, and `services/backend_check.py` (`_poll_model_and_digest`) with injectable `sleep` for fast deterministic tests.
- **`httpx`** standardizes all generic OpenAI-compatible HTTP transport across `adapters/backends.py`, `adapters/ollama.py`, `adapters/backend_probe.py`, and `adapters/github_workflow.py` (chosen over `openai>=3` which adds `httpx2` + Rust `jiter`, keeping one `httpx` stack across all adapters). Removed `requests` and `urllib3` from `pixi.toml` and `experiment/src/experiment/` (and test mocks).
- **`jenkspy`** replaces the ~100 LOC hand-rolled Fisher–Jenks DP behind `experiment/src/experiment/adapters/jenks.py` while keeping `validate_jenks_inputs` pure inside `experiment/src/experiment/domain/jenks.py`. Chosen over `mapclassify.FisherJenks` because Hypothesis property fuzzing uncovered a genuine float64 catastrophic-cancellation bug in `mapclassify`'s pure-Python fallback (plus its Numba `UserWarning`), whereas `jenkspy` 0.4.1 ships prebuilt `cp312`/`cp313` wheels for `linux-64`/`osx-arm64`/`win-64`, passes all Hypothesis checks, emits 0 warnings, and matches `cartography-jenks-001` bit-for-bit.
- **`tabulate`** renders GitHub-Flavored Markdown tables in `experiment/src/experiment/services/workflow_summary.py`.
- **`filelock`** guards cross-process writes (`write_json`, `append_jsonl`, `write_jsonl`) in `experiment/src/experiment/adapters/run_store.py` via temp-dir keyed lock files (so cell/harvest artifact inventories stay clean).
- **`Task.model_json_schema()` parity** verified against `experiment/tasks/schema-v1.json` in `experiment/tests/domain/test_task.py` (required keys, property names, and `TaskFamily` enum values).
- **`import-linter`** updated to forbid `diskcache`, `tenacity`, `jenkspy`, `mapclassify`, `filelock`, and `tabulate` inside `experiment.domain`.
<!-- SECTION:NOTES:END -->
