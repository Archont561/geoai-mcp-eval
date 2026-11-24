---
title: Experiment analysis (raw marimo notebook)
short_title: Experiment analysis (raw)
description: >-
  Raw marimo notebook behind the pilot/study analysis: the flat binary
  predicate matrix loaded from a validated RunArchive zip via GitHubRunClient,
  Task Success Rate (TSR / WSZ) and Mean Predicate Score (MPS / OQS) per trial
  and per paradigm × task cell, pass_at_k, and the Jenks ground truth used to
  read cartography-family failures. Cells hydrate in the browser; no network
  calls at build time or view time. Every embedded row is a clearly labelled
  illustration, never a pinned study result.
---

This is the raw, re-executable source behind the analysis pages—the narrative and the code,
nothing tidied away. **No pinned study run has executed yet**, so the matrix embedded below is an
*illustration*: six synthetic rows (two paradigms × three tasks, every predicate `0`) that exist
only so the cells render and the plumbing is visible. Nothing on this page is a finding. Cells
execute at build time and hydrate in the browser offline—CI spends no compute on runs, and no
run data is collected at read time. All text on this site is CC BY-SA 4.0.

Code and schema identifiers use the English experiment ontology (`task_success` / `TSR` for
study `WSZ`; `predicate_score` / `MPS` for study `OQS`; `paradigm` `typed_mcp` / `codegen` for
Arms `A` / `B`; `enforcement_level` `none`..`transactional` for `N0`..`N4`; `pass_at_k` for
`pass^k`). To refresh the embedded snapshot from a GitHub Actions `RunArchive` zip, see the
`GitHubRunClient` recipe below.

## Cell 1 — Inputs: the flat binary predicate matrix snapshot

**Intent.** The matrix produced by `RunDataset.predicates_df()`. One row per measured trial
(`run_id`, `trial_id`, `task_id`, `paradigm`, `enforcement_level`, `repetition`), plus one `0`/`1`
column per named predicate, columns sorted (`feature_count`, `natural_breaks`, `point_axis_order`,
`touches`). Predicate names come 1:1 from the `predicate` key of each oracle assertion in the
task YAMLs—the single source of truth. Missing or failed assertions score `0` (strict `TSR`/`WSZ`
semantics; never impute, never `NaN`). **Cross-task zero semantics:** trials also score `0` for
predicates belonging to *other* tasks, so always filter by `task_id` (or restrict to
`TASK_PREDICATES[task_id]`) before averaging predicate pass rates, `task_success`, or
`predicate_score`.

```{marimo} python
import json

import marimo as mo
import pandas as pd

MATRIX_JSON = r"""[
{"run_id":"illustration","trial_id":"analysis-de9im-001/typed_mcp/semantic_repair/rep-1","task_id":"analysis-de9im-001","paradigm":"typed_mcp","enforcement_level":"semantic_repair","repetition":1,"feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration","trial_id":"analysis-de9im-001/codegen/none/rep-1","task_id":"analysis-de9im-001","paradigm":"codegen","enforcement_level":"none","repetition":1,"feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration","trial_id":"cartography-jenks-001/typed_mcp/semantic_repair/rep-1","task_id":"cartography-jenks-001","paradigm":"typed_mcp","enforcement_level":"semantic_repair","repetition":1,"feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration","trial_id":"cartography-jenks-001/codegen/none/rep-1","task_id":"cartography-jenks-001","paradigm":"codegen","enforcement_level":"none","repetition":1,"feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration","trial_id":"prep-axis-order-001/typed_mcp/semantic_repair/rep-1","task_id":"prep-axis-order-001","paradigm":"typed_mcp","enforcement_level":"semantic_repair","repetition":1,"feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration","trial_id":"prep-axis-order-001/codegen/none/rep-1","task_id":"prep-axis-order-001","paradigm":"codegen","enforcement_level":"none","repetition":1,"feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0}]"""

matrix = pd.DataFrame(json.loads(MATRIX_JSON))
print(matrix.shape)
matrix
```

## Cell 2 — Task Success (`task_success` / WSZ) per trial

**Result.** `task_success = 1` iff every assertion of the task's oracle passes—here:
`analysis-de9im-001` → `touches`; `prep-axis-order-001` → `feature_count` **and**
`point_axis_order`; `cartography-jenks-001` → `natural_breaks`. The illustration rows all fail,
so every listed `task_success` is `0` and `TSR = 0.0000`. This is expected for placeholder rows,
not a measurement.

```{marimo} python
TASK_PREDICATES = {
    "analysis-de9im-001": ["touches"],
    "prep-axis-order-001": ["feature_count", "point_axis_order"],
    "cartography-jenks-001": ["natural_breaks"],
}


def task_success(row: pd.Series) -> int:
    """Strict binary task success (WSZ): 1 iff every named predicate passes."""
    return int(all(row[predicate] == 1 for predicate in TASK_PREDICATES[row["task_id"]]))


per_trial = matrix[["trial_id", "task_id", "paradigm", "enforcement_level", "repetition"]].copy()
per_trial["task_success"] = matrix.apply(task_success, axis=1)
print(f"TSR over {len(per_trial)} illustration rows = {per_trial['task_success'].mean():.4f}")
per_trial
```

## Cell 3 — Predicate Score (`predicate_score` / OQS) per trial

**Result.** `predicate_score = mean(assert pass_i)` over the task's own named predicates, ∈ [0, 1];
per-cell contract reports mean **and** median (bimodal pass/fail skew expected with real data).
Illustration rows give `predicate_score = 0.0000` everywhere; the mean/median split the contract
asks for is still computed below so the cells are ready for real rows.

```{marimo} python
def predicate_score(row: pd.Series) -> float:
    predicates = TASK_PREDICATES[row["task_id"]]
    return float(pd.Series([row[p] for p in predicates]).mean())


per_trial["predicate_score"] = matrix.apply(predicate_score, axis=1)
print(
    f"MPS mean = {per_trial['predicate_score'].mean():.4f} · "
    f"median = {per_trial['predicate_score'].median():.4f}"
)
per_trial
```

## Cell 4 — Aggregates per `task_id × paradigm × enforcement_level` cell

**Result.** Mirrors `RunDataset.cell_summary_df()`: `n_trials`, `task_success_rate` (TSR / WSZ̄),
`predicate_score_mean` (MPS / OQS̄), `predicate_score_median`, and `pass_at_k` (all `k` trials in
the cell pass). Repetitions per cell in the preregistered study grid are `r = 4` (pilot `r = 2`);
the illustration carries one synthetic row per cell, so every `pass_at_k` is `False` and rates
are `0`.

```{marimo} python
cell = (
    per_trial.groupby(["task_id", "paradigm", "enforcement_level"], as_index=False)
    .agg(
        n_trials=("trial_id", "count"),
        task_success_rate=("task_success", "mean"),
        predicate_score_mean=("predicate_score", "mean"),
        predicate_score_median=("predicate_score", "median"),
    )
)
cell["pass_at_k"] = cell.apply(
    lambda r: bool(r["task_success_rate"] == 1.0 and r["n_trials"] > 0), axis=1
)
cell.round(4)
```

## Cell 5 — TSR and MPS by `paradigm × task_id`

**Result.** Same aggregates as bars. With illustration rows every bar is zero; the chart is wired
to `cell` so it renders real values the moment the embedded snapshot is replaced. Symlog is
unnecessary at 0/1 heights—linear scale, zero baseline.

```{marimo} python
import altair as alt

order = cell["task_id"].unique().tolist()
lng = cell.melt(
    id_vars=["task_id", "paradigm"],
    value_vars=["task_success_rate", "predicate_score_mean"],
    var_name="metric",
    value_name="value",
)
chart = (
    alt.Chart(lng)
    .mark_bar()
    .encode(
        x=alt.X("task_id:N", sort=order, title=None),
        y=alt.Y("value:Q", title="illustration mean (0–1)", scale=alt.Scale(domain=[0, 1])),
        xOffset="paradigm:N",
        color=alt.Color("paradigm:N", title="Paradigm"),
        row=alt.Row("metric:N", title=None),
        tooltip=["task_id:N", "paradigm:N", "metric:N", alt.Tooltip("value:Q", format=".4f")],
    )
    .properties(width=320, height=130)
)
chart
```

## Cell 6 — Jenks ground truth for `cartography-jenks-001`

**Result.** The oracle's own break set and class assignments for the Natural Earth 1:110m POP_EST
fixture (public domain), `class_count = 4`, class 1 = lowest population:

| ISO_A3 | POP_EST | class |
|---|---:|---:|
| LTU | 2 786 844 | 1 |
| SVK | 5 454 073 | 1 |
| AUT | 8 877 067 | 1 |
| HUN | 9 769 949 | 1 |
| CZE | 10 669 709 | 1 |
| POL | 37 970 874 | 1 |
| UKR | 44 385 155 | 1 |
| DEU | 83 132 799 | 2 |
| JPN | 126 264 931 | 2 |
| USA | 328 239 523 | 3 |
| IND | 1 366 417 754 | 4 |
| CHN | 1 397 715 000 | 4 |

Upper class bounds, ascending: `44 385 155.0`, `126 264 931.0`, `328 239 523.0`, `1 397 715 000.0`.
Any paradigm whose `natural_breaks` scores `1` reproduced exactly these breaks and
assignments—nothing else passes this predicate.

```{marimo} python
JENKS_BREAKS = [44385155.0, 126264931.0, 328239523.0, 1397715000.0]
POP = {
    "LTU": 2786844, "SVK": 5454073, "AUT": 8877067, "HUN": 9769949,
    "CZE": 10669709, "POL": 37970874, "UKR": 44385155, "DEU": 83132799,
    "JPN": 126264931, "USA": 328239523, "IND": 1366417754, "CHN": 1397715000,
}
CLASS = {c: [] for c in (1, 2, 3, 4)}
for code, klass in json.loads(r"""{"LTU":1,"SVK":1,"AUT":1,"HUN":1,"CZE":1,"POL":1,"UKR":1,"DEU":2,"JPN":2,"USA":3,"IND":4,"CHN":4}""").items():
    CLASS[klass].append(code)

print("breaks:", JENKS_BREAKS)
for klass in (1, 2, 3, 4):
    print(f"class {klass}: {sorted(CLASS[klass])}")
```

## Cell 7 — Failure classes (coding hook pending real logs)

**Result.** No study run logs have been coded yet. The four §6.7 failure classes and the counts
to tally from `RunDataset.assertions_df()` and lazy `dataset.trial(trial_id).transcript` drill-downs
at freeze:

```{marimo} python
FAILURE_CLASSES = pd.DataFrame(
    [
        {"class": "interface_adjacent", "definition": "tool pick/params wrong; right idea, wrong call", "trials_coded": 0},
        {"class": "workflow_silent", "definition": "CRS/units/aggregation mistake, no error raised", "trials_coded": 0},
        {"class": "hallucinated_structure", "definition": "invented dataset schema/field/method", "trials_coded": 0},
        {"class": "other", "definition": "anything else; stratum-logged", "trials_coded": 0},
    ]
)
mo.md(
    "**Failure classes (§6.7).** Double-code ≥15 % of rows. "
    "Trajectory classes (`hybrid_mcp_code` / `code_driving_mcp`): "
    "`typed_only`, `code_only`, `mixed`; collapse rate = P(`code_only`) in `hybrid_mcp_code`."
)
FAILURE_CLASSES
```

## Caveats

- Nothing on this page is a result. `TSR`/`MPS` here are illustration arithmetic over synthetic
  all-zero rows.
- Paradigm definitions, freeze order, and the scoring contract live in
  [Experiment setup](../study/experiment.md) and
  [Measurements and scoring](../study/measurements-scoring.md); this page implements, it does not
  redefine.
- Snapshot refresh discipline: replace `MATRIX_JSON`, re-derive every caption, and never hand-edit
  a derived number.
- Results, when they exist, graduate to the findings pages only after pre-freeze review; this page
  remains the raw audit view.

:::{dropdown} Refreshing from GitHub Actions (`GitHubRunClient` + `RunDataset`)
The cells above never touch the network and never read `results/` at build time. To pull a
completed workflow run's single `experiment-run-<run_id>.zip` artifact (cached under
`.cache/gh-runs/`) or open a local archive offline, run this recipe outside the site, then paste
the printed JSON into `MATRIX_JSON` and rewrite the captions in Cells 2–5:

```bash
PYTHONPATH=experiment/src pixi run python - <<'PYEOF'
from experiment.analysis import GitHubRunClient

client = GitHubRunClient()
# Online (cached under .cache/gh-runs/): client.load_latest() or client.load_run(<run_id>)
# Offline local zip: client.load_zip("path/to/experiment-run-<run_id>.zip")
with client.load_latest() as dataset:
    print(dataset.cell_summary_df())
    print(dataset.predicates_df().to_json(orient="records"))
    # Lazy failure drill-down (verified via SHA-256 on demand):
    # first_trial = next(iter(dataset.run.trials))
    # print(dataset.trial(first_trial).transcript[:3])
PYEOF
```

`RunDataset.predicates_df()` enforces the same strict semantics the cells above implement: a
trial missing a named predicate's assertion scores `0` (never `NaN`), and assertions with no
`predicate` mapping raise `ValueError`—catching YAML drift before analysis time.

The Jenks constants in Cell 6 are regenerated from the fixture with:

```bash
PYTHONPATH=experiment/src pixi run python - <<'PYEOF'
from pathlib import Path

from experiment.oracle._jenks import jenks_assignments

fixture = Path("experiment/tasks/fixtures/cartography/countries.geojson")
breaks, assignments = jenks_assignments(fixture, "ISO_A3", "POP_EST", 4)
print(breaks)
print(assignments)
PYEOF
```

:::
