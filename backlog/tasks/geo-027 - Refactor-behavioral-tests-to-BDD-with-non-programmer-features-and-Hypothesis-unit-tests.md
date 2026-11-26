---
id: GEO-027
title: Refactor behavioral tests into non-programmer BDD scenarios and restrict unit tests to Hypothesis property tests
status: Done
assignee: []
created_date: '2026-11-24T00:00:00Z'
labels:
  - testing
  - bdd
  - hypothesis
  - documentation
  - architecture
milestone: m-5
dependencies:
  - GEO-023
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Rebalance the repository's test architecture around two crisp, non-overlapping layers — **human-readable BDD scenarios** for all user- and researcher-visible behavior, and **Hypothesis property-based unit tests** for pure mathematical, serialization, and invariant properties — while rewriting and expanding all `.feature` files using the `.agents/skills/bdd-scenarios/SKILL.md` discipline so non-programmers (GIS researchers, domain reviewers, thesis advisors) can read, review, and validate every behavioral specification without needing to understand Python internals, CLI flags, or JSON schemas.

### Current state & imbalance

1. **Test distribution today:**
   - `experiment/tests/`: `1` BDD scenario module (`test_cli_scenarios.py`, binding `5` `.feature` files), `24` Hypothesis property test modules, `43` example-based unit test modules (without Hypothesis), and `3` structural/gate modules (`test_architecture.py`, `test_clean_code_gate.py`, `test_smoke.py`).
   - `experiment-qgis-plugin/tests/`: `2` BDD scenario modules (`test_plugin_scenarios.py`, `test_review_scenarios.py`, binding `5` `.feature` files), `3` Hypothesis property test modules, and `13` example-based unit test modules.
   - Example-based behavioral workflows (e.g., backend preflight error classification, SSH tunnel failure modes, LLM cache hits/misses/digest invalidation, token-cap aborts, run archive packing/merging/tamper detection, dataset DataFrame projections, GitHub run downloads, oracle grading edge cases, and plugin session lifecycle edge cases) currently live inside Python unit tests rather than executable Gherkin specifications.

2. **Existing `.feature` files leak programmer jargon:**
   - Several existing scenarios in `experiment/features/` (`command-line.feature`, `pilot-suite.feature`, `prototype-runs.feature`, `qgis-sandbox.feature`, `workflow.feature`) and `experiment-qgis-plugin/features/` (`hello.feature`, `host-observation.feature`, `human-baseline.feature`, `post-session-review.feature`, `session-panel.feature`) reference raw CLI command strings (`"tasks validate --root {suite}"`), Python module/package details (`python -m experiment`, `PyQGIS`, `RunArchive zip`), or step counts that exceed the 3–7 step guideline.
   - `experiment/features/README.md` still lists removed/stale files (`analysis.feature`, "the greeting command").

### Target testing architecture & `.agents/skills/bdd-scenarios/SKILL.md` standard

1. **Non-programmer-first BDD feature specifications (`experiment/features/*.feature` & `experiment-qgis-plugin/features/*.feature`):**
   - Apply every principle from `.agents/skills/bdd-scenarios/SKILL.md`:
     - **Declarative, business-focused domain language:** Describe *what* the GIS researcher, human participant, or study reviewer observes and expects — never *how* Python, Typer flags, HTTP calls, or JSON keys implement it.
     - **Specific & independent scenarios:** One behavior per scenario, 3–7 steps each, zero cross-scenario ordering dependencies.
     - **`Rule:`-grouped acceptance criteria:** Group happy paths and edge cases under clear domain `Rule:` headings so non-technical readers can scan study guarantees at a glance.
     - **Consistent tags:** Organize features and scenarios with clear domain tags (`@tasks`, `@oracle`, `@runs`, `@archive`, `@preflight`, `@analysis`, `@qgis-sandbox`, `@human-baseline`, `@review`, `@smoke`, `@edge-case`).
   - Expand feature coverage so behavioral flows currently tested only in example-based unit tests become executable Gherkin specifications bound via `pytest-bdd` (using shared `unittest.mock` fake fixtures from `fakes.py` and workspace fixtures from `fixtures.py` behind the step definitions):
     - `experiment/features/`:
       - `command-line.feature` (rewritten in researcher language)
       - `pilot-suite.feature` (task suite validity, schema & fixture integrity, family/trap coverage)
       - `oracle-grading.feature` (axis-order trap detection, topology DE-9IM grading, Jenks classification grading, 3x determinism gate)
       - `experiment-runs.feature` (scripted & model-driven MCP vs. codegen runs, token-budget enforcement, digest-pinned response caching, error non-caching)
       - `run-archives.feature` (packing, merging parallel run fragments, tamper detection, lazy trial inspection)
       - `backend-preflight.feature` (SSH tunnel verification, model digest pinning, rate-limit retries, auth & token-limit diagnostics)
       - `analysis-dataset.feature` (loading archived runs from GitHub or disk into measurement, predicate, assertion, and cell-summary tables)
       - `qgis-sandbox.feature` (PyQGIS availability check and isolated script execution)
       - `workflow.feature` (end-to-end researcher pass from suite check through archived run)
     - `experiment-qgis-plugin/features/`:
       - Audit and refine `hello.feature`, `host-observation.feature`, `human-baseline.feature`, `post-session-review.feature`, and `session-panel.feature` using `Rule:` blocks, plain GIS-operator phrasing, and 3–7 step scenarios while preserving all existing behavioral guarantees.

2. **Unit tests strictly scoped to Hypothesis property-based tests:**
   - Non-BDD unit tests exclusively test **general properties and invariants** using Hypothesis `@given(...)` (serialization round-trips, algebraic/statistical properties like Fisher-Jenks optimality and monotonicity, deterministic hashing and cache keys, token accumulation and cap math, path traversal containment, enum exhaustion and parsing, merge commutativity/idempotence, atomic I/O round-trips, and deduplication invariants).
   - Migrate example-based behavioral unit tests out of the `43 + 13` non-Hypothesis unit files into the BDD feature/step suites (or generalize pure invariant checks into Hypothesis `@given(...)` tests), keeping only the dedicated structural/repo-gate tests (`test_smoke.py`, `test_architecture.py`, `test_clean_code_gate.py`) separate.
   - Update `experiment/tests/test_architecture.py` so the structural gate enforces the new testing contract cleanly (every behavioral feature passes `gherlint` and binds cleanly; unit test modules contain Hypothesis property tests rather than ad-hoc example-only unit tests, while updating the 1:1 module-mirror rule so BDD-covered adapter/CLI/service modules are accounted for explicitly without redundant boilerplate unit files).

3. **Step-definition ergonomics & fixture reuse:**
   - Keep `pytest-bdd` step definitions modular by domain (e.g. `experiment/tests/bdd/` or cohesive `test_*_scenarios.py` modules) and inject all collaborator doubles via the shared `unittest.mock` fake fixtures (`fakes.py`, `fixtures.py`, `plugin_harness.py`) instead of ad-hoc helpers.
   - Update `experiment/features/README.md` (and add/update `experiment-qgis-plugin/features/README.md`) to document the non-programmer BDD authoring guide referencing `.agents/skills/bdd-scenarios/SKILL.md`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 All existing `.feature` files under `experiment/features/` and `experiment-qgis-plugin/features/` are reviewed and updated following `.agents/skills/bdd-scenarios/SKILL.md` so every feature uses plain, declarative domain language understandable by non-programmers (zero raw Python symbols, JSON keys, or cryptic CLI flags in scenario prose), `Rule:`-grouped acceptance criteria, 3–7 step scenarios, and clean domain tags.
- [x] #2 Behavioral test cases currently living in example-based unit tests (oracle grading & determinism, experiment runs & token-cap/cache semantics, run archive packing/merging/tamper detection, backend preflight & SSH/Ollama/OpenRouter diagnostics, analysis dataset & GitHub client loading, and QGIS plugin session/review/host behavior) are migrated into executable `.feature` files and modular `pytest-bdd` step bindings backed by shared pytest & `unittest.mock` fake fixtures.
- [x] #3 Non-BDD unit test modules (outside the explicit structural gates `test_smoke.py`, `test_architecture.py`, `test_clean_code_gate.py`) are strictly scoped to Hypothesis `@given(...)` property-based tests verifying mathematical, validation, serialization, and security invariants; redundant example-only unit test files are removed after their behaviors are covered by BDD scenarios.
- [x] #4 `experiment/tests/test_architecture.py` enforces the testing pyramid contract cleanly (accounting for BDD-covered modules vs. Hypothesis property unit modules) and verifies all `.feature` files have bound scenarios.
- [x] #5 `experiment/features/README.md` (and `experiment-qgis-plugin/features/README.md`) accurately index all feature files and document the non-programmer BDD guidelines from `.agents/skills/bdd-scenarios/SKILL.md`.
- [x] #6 `pixi run tools run check` (including `alint`, `ruff`, `clean_code`, `import-linter`, `mypy`, `pytest` with `>=90%` coverage), `gherlint`, `md`, and `links` all pass with zero errors and zero lost behavioral coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Audit & classify existing tests and features:** Map every non-Hypothesis test file (`43` in `experiment/tests/`, `13` in `experiment-qgis-plugin/tests/`) to either a target BDD `.feature` scenario (user/system behavior) or a Hypothesis `@given(...)` property test (pure invariant), and audit all `10` existing `.feature` files against `.agents/skills/bdd-scenarios/SKILL.md`.
2. **Rewrite existing `.feature` files for non-programmer readability:** Update `experiment/features/{command-line,pilot-suite,prototype-runs,qgis-sandbox,workflow}.feature` and `experiment-qgis-plugin/features/{hello,host-observation,human-baseline,post-session-review,session-panel}.feature` with `Rule:` blocks, declarative researcher/operator prose, 3–7 steps per scenario, and consistent tags; keep `gherlint` green.
3. **Add new BDD features & modular step definitions for migrated behaviors:** Author `oracle-grading.feature`, `experiment-runs.feature`, `run-archives.feature`, `backend-preflight.feature`, and `analysis-dataset.feature` under `experiment/features/` and bind them via modular `pytest-bdd` scenario modules reusing `fixtures.py` and `fakes.py` (`unittest.mock`).
4. **Restrict unit tests to Hypothesis property tests & prune migrated example-only files:** Convert remaining pure invariant checks to `@given(...)` properties, remove example-only unit tests whose behaviors now live in BDD features, and update `test_architecture.py` to enforce the BDD + Hypothesis testing contract cleanly.
5. **Update feature READMEs & run all quality gates:** Refresh `experiment/features/README.md` and `experiment-qgis-plugin/features/README.md`, then run `pixi run tools run fmt`, `check`, `md`, `links`, and `gherlint` to verify `0` violations and `>=90%` coverage.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
- Rewrote the original feature specifications and added executable specifications for oracle grading, experiment runs, run archives, backend preflight, and analysis datasets. Scenario steps reuse the experiment fixtures and plugin harness.
- Replaced example-only unit modules with BDD scenarios or general Hypothesis invariants. The architecture gate checks feature bindings, rule grouping, scenario step counts, explicit BDD module mappings, and the property-test pyramid; it also rejects fixed-only `just` strategies.
- Audited the migration against the pre-migration `a96ac74` snapshot. Temporarily replayed 380 tests from 87 removed or changed non-BDD modules; all passed. After restoring a missing GIS-host scenario and the environment fallback check, every production source line exercised by that replay was also exercised by the migrated suite. Line coverage is evidence, not a substitute for checking behavioral assertions. Temporary audit tests were removed.
- Final pinned verification: `fmt` and `check` passed with 583 tests and 94.11% coverage; both feature directories passed Gherkin lint; `md`, `links`, and `prose` passed. Prose reported 134 advisory warnings and no errors.
<!-- SECTION:NOTES:END -->
