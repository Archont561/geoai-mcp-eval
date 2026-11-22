# Decision: Task-suite YAML schema v1

## Status

Proposed (to freeze at v1.0-prereg)

## Decision

The task suite uses YAML schema v1 with these required fields:

- `id` — stable, unique across the suite
- `family` — P (prepare/IO), A (analysis), or C (cartography)
- `difficulty_rubric` — `n_tools_human`, `n_steps_human`
- `provenance` — source, licence, contamination tag
- `human_baseline` — produced before agent runs
- `oracle` — >=3 determinism runs, tiered assertions
- `budget_bounds` — per-task budget limits

Mandatory traps: raster, topology/DE-9IM, CRS/axis-order, Jenks/classification,
zonation/aggregation (MAUP), NoData.

Licensing: inherited GIS StackExchange tasks are CC BY-SA 4.0 (attribution
mandatory); author-constructed tasks are CC0.

## Rationale

From `docs/study/experiment.md`: schema v1 is frozen at freeze; CI-enforced
pre-freeze via the task-suite validator (GEO-002).

## Alternatives considered

None — schema v1 is the frozen design from the specification.
