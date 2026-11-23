# Prepare-task refactor plan (`prep-axis-order-001` and the P family)

## Status

Proposed — **not applied**. Owner decision required before any edit to the task
suite. Complements GEO-005 (pre-freeze audit) and GEO-006 (freeze tag).

## Why

`prep-axis-order-001` asks for two things: select the `ISO_A3 = POL` feature,
then write its representative point in RFC 7946 order. The oracle scores both.
But the shipped fixture `fixtures/prepare/poland.geojson` contains **one**
feature, so the first instruction has nothing to select and the rubric that
prices it (`n_tools_human: 2`, `n_steps_human: 3`) is not measurable against
the artefact that gets scored.

This is not a scoring bug — the oracle is correct and does discriminate. It is
a **construct-validity** defect: the task's stated difficulty is not the
difficulty the harness can observe, and two of its three nominal steps are free.

Everything below was verified against the shipped suite, not argued from the
YAML. Reproduction commands are given so a reviewer can re-run them.

### Evidence

**E1 — the fixture has one feature.** `fixtures/prepare/poland.geojson` holds a
single `Feature` (`ISO_A3: POL`, plus `ADMIN`, `POP_EST`). The prompt's filter
step is therefore a no-op: an agent that never reads the property names still
produces the correct output.

**E2 — one operation clears the whole task.** `gis_ops.representative_point`
already copies every input property onto the output point
(`_fc_from(..., [f.get(_PROPS) ...])`). Calling it once on the fixture returns
exactly the scored artefact — representative point
`(19.07626726679996, 51.8844175)`, all three properties intact — satisfying
`single-output-feature` *and* `representative-point-axis-order`, including
`preserve_fields: [ADMIN, ISO_A3]`. The observable floor is **one tool call,
one step**, not two and three.

**E3 — the oracle itself is sound.** Mutating the real artefact and rescoring
shows the assertions bite:

| Mutation | `single-output-feature` | `representative-point-axis-order` |
|---|---|---|
| none (baseline) | pass | pass |
| `[lon, lat]` → `[lat, lon]` | pass | **fail** (`point is [51.88…, 19.07…]`) |
| drop `ADMIN` | pass | **fail** (`must preserve ADMIN='Poland'`) |
| empty `properties` | pass | **fail** |
| two output features | **fail** | **fail** |
| shift longitude by 0.001° | pass | **fail** |

So the defect is *what the task asks for*, not *what the oracle checks*. The
refactor should change the task and fixture, and leave the evaluator alone.

**E4 — `preserve_fields` is not discriminating here.** Because E2 holds, an
agent that never thinks about attributes still passes the property check: the
tool does the attribute handling for it. The assertion is only meaningful when
the pipeline contains a step that *could* drop properties — which a
filter-then-point pipeline is, and a single point call is not.

## Proposals

Ordered by ratio of validity gained to disruption caused. P1 and P2 fix the
defect; P3–P5 harden the family. Nothing here changes an oracle *threshold*;
`tolerance_degrees: 1e-6` stays as it is, in line with the freeze-order rule
("tune task bugs only, never oracle thresholds post-hoc").

### P1 — give the filter step something to filter (recommended)

Repoint `prep-axis-order-001` at a two-feature fixture so `ISO_A3 = POL` is a
real selection with a real alternative. The obvious candidate already exists:
`fixtures/analysis/poland-czechia.geojson` (POL + CZE). Its POL feature was
checked byte-identical to the prepare fixture's POL feature — same geometry,
same properties — so the expected point does not move:

- Expected point: unchanged, `(19.07626726679996, 51.8844175)`.
- `tolerance_degrees`: unchanged.
- Oracle assertions: unchanged, only the `fixture:` values repoint.
- `n_tools_human: 2`, `n_steps_human: 3`: now honest — filter, then point,
  with a preserved attribute path.

This was prototyped end-to-end against a scratch copy of the suite. With the
two-feature fixture, a filtered pipeline passes both assertions and an
unfiltered pipeline (point every feature) fails both. `pilot validate` still
reports `passed: True`, 3 tasks, all traps covered.

Two ways to land it, and the choice is a research decision, not an engineering
one:

- **P1a — share the fixture.** Point the task at
  `fixtures/analysis/poland-czechia.geojson`. No new bytes, no new hash; the
  prepare and analysis tasks then share an input. Cheapest, but couples two
  tasks: a future fixture edit for one silently changes the other's input.
- **P1b — copy it (preferred).** Add
  `fixtures/prepare/poland-czechia.geojson` (6,873 B,
  SHA-256 `cf33121481499488417f46c40f6b0ededd9c5bd13470670daa15a4cda307b0b1`).
  Independent fixtures keep the tasks independently editable and keep the
  provenance story per-task. Costs one row in the README hash table.

**P1 must be accompanied by a rubric note**, not just a fixture swap: record
that `n_tools_human: 2` counts *filter + representative point* and that the
filter is now non-vacuous. Otherwise the next reader inherits the same
unexplained numbers.

### P2 — make the axis-order trap test what it says

`required_traps: [crs-axis-order]` is declared, and E3 shows a lat/lon swap
does fail. That part is real. What is missing is an assertion that talks about
*ordering* as a property, separately from the point's value. Today a swapped
output fails because the coordinates differ, which means the trap and the
accuracy check are the same check. An agent could fail the trap for a reason
that reads like an accuracy miss, and the message does not name the trap.

Proposal: add a third assertion to the same task —

- `id: longitude-within-range`, `type: representative_point_matches` is the
  wrong shape for this, and inventing a one-field oracle type for it would be
  worse. Instead: keep the two assertions as they are, and **add the trap name
  to the failure message** of `representative-point-axis-order` when the
  submission is the exact transposition of the reference point (within
  tolerance). That is a message change in `_evaluators.py`, no threshold change,
  and it makes the predicate matrix's `point_axis_order` column defensible when
  a row is examined post hoc.

Deferred alternative, if a message change is judged insufficient: a distinct
`type: coordinate_order` assertion that checks `-180 ≤ x ≤ 180`,
`-90 ≤ y ≤ 90`, and that the point is not the transposition of the reference.
This needs a schema version bump and a new evaluator, so it should not ride
along with P1.

### P3 — one behavioural checkpoint for the family

Add a plugin/CLI Gherkin scenario that pins the intent of the fix rather than
the fixture bytes: *a prepare task whose input holds more than one feature must
still be scorable to exactly one output feature*. A scenario like this is the
regression guard against a future fixture being shrunk back to one feature
(this is precisely how the current defect would have been caught). It belongs
in `experiment/features/pilot-suite.feature`, not in a unit test, because it
is a statement about the instrument.

### P4 — the other P-family candidate, and the catalogue gaps

Before the family is frozen it should have more than one member, or "P family
coverage" is a formality met by a single task. The documented catalogue gaps
(field calculator, merge, ideally point distance) are P-family shaped:
attribute carry-through and layer merging both live in prepare/IO work.

Sequencing matters more than the choice: these are **new tasks**, which means
new rubrics, new fixtures, and new human-reference records. They cannot be
added after `v1.0-prereg` without reopening the freeze. If a second P task is
in scope at all, it has to land before GEO-006, and its `human_baseline` has to
be produced by the GEO-004 protocol — which is the real constraint, not the
code.

### P5 — traps the pilot does not represent

`experiment/tasks/README.md` already states that raster, zonation/MAUP, and
NoData belong to a proposed expanded suite and are **not** covered by the three
pilot tasks. That is honest and should stay. This plan only records that P1–P4
do not change that statement: adding a second prepare task does not close the
raster, MAUP, or NoData gaps, and no freeze document should imply it does.

## Consequential edits (the checklist)

If P1b + P2 are approved, this is the complete change set:

1. `experiment/tasks/fixtures/prepare/poland-czechia.geojson` — new file.
2. `experiment/tasks/prep-axis-order-001.yaml` — `fixtures.input` and both
   assertion `fixture:` values repoint; rubric numbers get their note.
3. `experiment/tasks/README.md` — the fixture SHA-256 table gains a row (or has
   its `prep-axis-order-001` row replaced); the hash is pinned there and a
   fixture change without a table change is a failing audit.
4. `experiment/tests/cli_harness.py` — `write_point_artifact` reads
   `["features"][0]`; it must select `ISO_A3 == "POL"` instead, or the
   determinism-gate fixture silently starts asserting against Czechia.
5. `experiment/src/experiment/oracle/_evaluators.py` — the transposition
   message (P2 only).
6. `experiment/features/workflow.feature` — the P3 scenario.
7. GEO-005 pre-freeze audit — new fixture checksum recorded, with the change
   described as a pre-freeze task-bug fix.

Item 4 is the one that will be missed. It is a two-line change and it fails
loudly, which is the good case; the bad case is that `write_point_artifact`
keeps working by accident because the first feature is still POL in the copy.
Either way it deserves a reviewer's attention.

## Explicitly out of scope

- Changing `tolerance_degrees`, or any oracle threshold, in either direction.
- Retiring `prep-axis-order-001` and replacing it with a fresh task ID. That
  would discard the existing provenance chain for a cosmetic gain; P1 gets the
  same validity for a fraction of the audit surface.
- Deleting the single-feature `fixtures/prepare/poland.geojson`. Keep it until
  the audit has recorded the transition; deleting it in the same commit makes
  the diff harder to review, not cleaner.

## Open decisions

1. **P1a or P1b?** Shared fixture (no new hash, coupled tasks) or a copy (one
   new hash row, independent tasks). Recommendation: P1b.
2. **Is P2 in scope now,** or does the message change wait for a schema v2
   alongside the coordinate-order assertion? Recommendation: message change
   now, assertion later.
3. **Is P4 in scope before freeze?** If yes it is a milestone-sized item
   (new task + fixture + human reference), not a refactor, and it should be
   filed as its own Backlog task rather than folded into this one.
4. **Does the frozen spec need to acknowledge the defect?** The task suite is
   pre-freeze, so the *fix* needs no supervisor sign-off. Whether
   `docs/study/experiment.md` should carry a line recording that a pilot task
   was found under-specified and corrected is a documentation judgement for the
   owner.
