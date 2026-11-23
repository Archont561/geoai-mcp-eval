---
id: doc-009
title: Experiment analysis (raw marimo notebook)
short_title: Experiment analysis (raw)
description: >-
  Raw marimo notebook behind the pilot/study analysis: the flat binary
  predicate matrix flattened from run results, WSZ and OQS per run and per
  arm×task cell, pass^k, and the Jenks ground truth used to read
  cartography-family failures. Cells hydrate in the browser; no network calls
  at build time or view time. No pinned runs exist yet — every matrix row is a
  clearly labelled illustration, never pilot data.
type: guide
created_date: '2026-11-22T00:00:00Z'
---

This is the raw, re-executable source behind the analysis pages—the narrative and the code,
nothing tidied away. **No pinned run has executed anywhere yet**, so the matrix embedded below
is an *illustration*: six synthetic rows (two arms × three tasks, every predicate 0) that exist
only so the cells render and the plumbing is visible. Nothing on this page is a finding. Cells
execute at build time and hydrate in the browser offline—CI spends no compute on runs, and no
run data is collected at read time. All text on this site is CC BY-SA 4.0. To refresh the
embedded matrix from real run output, see the regeneration notes below.

## Cell 1 — Inputs: the flat binary predicate matrix snapshot

**Intent.** The matrix. One row per cell (run × task), one 0/1 column per named predicate, columns sorted (`feature_count`, `natural_breaks`, `point_axis_order`, `touches`). Predicate names come from the `predicate` key of each oracle assertion in the task YAMLs—the single source of truth. Missing or failed assertions score 0 (strict WSZ semantics; never impute, never NaN). The rows printed here are the illustration described above; `results/` in the repository currently holds no `score.json` files.

```{marimo} python
import json

import marimo as mo
import pandas as pd

MATRIX_JSON = r"""[
{"run_id":"illustration-a-analysis-de9im-001","task":"analysis-de9im-001","arm":"A","driver":"ollama","model":"qwen2.5-coder:0.5b","feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration-b-analysis-de9im-001","task":"analysis-de9im-001","arm":"B","driver":"ollama","model":"qwen2.5-coder:0.5b","feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration-a-cartography-jenks-001","task":"cartography-jenks-001","arm":"A","driver":"ollama","model":"qwen2.5-coder:0.5b","feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration-b-cartography-jenks-001","task":"cartography-jenks-001","arm":"B","driver":"ollama","model":"qwen2.5-coder:0.5b","feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration-a-prep-axis-order-001","task":"prep-axis-order-001","arm":"A","driver":"ollama","model":"qwen2.5-coder:0.5b","feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0},
{"run_id":"illustration-b-prep-axis-order-001","task":"prep-axis-order-001","arm":"B","driver":"ollama","model":"qwen2.5-coder:0.5b","feature_count":0,"natural_breaks":0,"point_axis_order":0,"touches":0}]"""

matrix = pd.DataFrame(json.loads(MATRIX_JSON))
print(matrix.shape)
matrix
```

## Cell 2 — WSZ per run

**Result.** `WSZ = 1` iff every assertion of the task's oracle passes—here: `analysis-de9im-001` → `touches`; `prep-axis-order-001` → `feature_count` **and** `point_axis_order`; `cartography-jenks-001` → `natural_breaks`. The illustration rows all fail, so every listed WSZ is 0 and `WSZ̄ = 0.0000`. This is expected for placeholder rows, not a measurement.

```{marimo} python
TASK_PREDICATES = {
    "analysis-de9im-001": ["touches"],
    "prep-axis-order-001": ["feature_count", "point_axis_order"],
    "cartography-jenks-001": ["natural_breaks"],
}


def wsz(row: pd.Series) -> int:
    """Strict WSZ for one matrix row: 1 iff every named predicate passes."""
    return int(all(row[predicate] == 1 for predicate in TASK_PREDICATES[row["task"]]))


per_run = matrix[["run_id", "task", "arm"]].copy()
per_run["WSZ"] = matrix.apply(wsz, axis=1)
print(f"WSZ̄ over {len(per_run)} illustration rows = {per_run['WSZ'].mean():.4f}")
per_run
```

## Cell 3 — OQS per run

**Result.** `OQS = mean(assert pass_i)` over the task's own named predicates, ∈ [0, 1]; per-cell contract is mean **and** median (bimodal pass/fail skew expected with real data). Illustration rows give `OQS = 0.0000` everywhere; the mean/median split the contract asks for is still computed below so the cells are ready for real rows.

```{marimo} python
def oqs(row: pd.Series) -> float:
    predicates = TASK_PREDICATES[row["task"]]
    return float(pd.Series([row[p] for p in predicates]).mean())


per_run["OQS"] = matrix.apply(oqs, axis=1)
print(f"OQS mean = {per_run['OQS'].mean():.4f} · median = {per_run['OQS'].median():.4f}")
per_run
```

## Cell 4 — Aggregates per arm×task cell

**Result.** Per arm×task: `n` runs, `WSZ̄` (mean), `OQS̄` (mean), `OQS` median, and `pass^k` (all k runs in the cell pass). Runs per arm in a real grid is 4 (preregistered r = 4); the illustration carries no repetitions, so every `pass^k` is `False` and `WSZ̄`/`OQS̄` are 0.

```{marimo} python
cell = (
    per_run.groupby(["task", "arm"], as_index=False)
    .agg(
        n_runs=("run_id", "count"),
        WSZ_mean=("WSZ", "mean"),
        OQS_mean=("OQS", "mean"),
        OQS_median=("OQS", "median"),
    )
)
cell["pass^k"] = cell.apply(
    lambda r: bool(r["WSZ_mean"] == 1.0 and r["n_runs"] > 0), axis=1
)
cell.round(4)
```

## Cell 5 — WSZ̄ and OQS by arm × task

**Result.** Same aggregates as bars. With illustration rows every bar is zero; the chart is wired to `cell` so it renders real values the moment the embedded snapshot is replaced. Symlog is unnecessary at 0/1 heights—linear scale, zero baseline.

```{marimo} python
import altair as alt

order = cell["task"].unique().tolist()
lng = cell.melt(
    id_vars=["task", "arm"],
    value_vars=["WSZ_mean", "OQS_mean"],
    var_name="metric",
    value_name="value",
)
chart = (
    alt.Chart(lng)
    .mark_bar()
    .encode(
        x=alt.X("task:N", sort=order, title=None),
        y=alt.Y("value:Q", title="illustration mean (0–1)", scale=alt.Scale(domain=[0, 1])),
        xOffset="arm:N",
        color=alt.Color("arm:N", title="Arm"),
        row=alt.Row("metric:N", title=None),
        tooltip=["task:N", "arm:N", "metric:N", alt.Tooltip("value:Q", format=".4f")],
    )
    .properties(width=320, height=130)
)
chart
```

## Cell 6 — Jenks ground truth for `cartography-jenks-001`

**Result.** The oracle's own break set and class assignments for the Natural Earth 1:110m POP_EST fixture (public domain), class_count = 4, class 1 = lowest population:

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

Upper class bounds, ascending: `44 385 155.0`, `126 264 931.0`, `328 239 523.0`, `1 397 715 000.0`. Any arm whose `natural_breaks` scores 1 reproduced exactly these breaks and assignments—nothing else passes this predicate.

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

**Result.** No run logs exist, so nothing has been coded. The four §6.7 failure classes and the counts to tally from `score.json` assertion messages at freeze:

```{marimo} python
FAILURE_CLASSES = pd.DataFrame(
    [
        {"class": "interface-adjacent", "definition": "tool pick/params wrong; right idea, wrong call", "runs_coded": 0},
        {"class": "workflow-silent", "definition": "CRS/units/aggregation mistake, no error raised", "runs_coded": 0},
        {"class": "hallucinated structure", "definition": "invented dataset schema/field/method", "runs_coded": 0},
        {"class": "other", "definition": "anything else; stratum-logged", "runs_coded": 0},
    ]
)
mo.md(
    "**Failure classes (§6.7).** Double-code ≥15 % of rows. "
    "Trajectory classes (arms C/D): `typed-only`, `code-only`, `mixed`; "
    "collapse rate = P(code-only) in arm C."
)
FAILURE_CLASSES
```

## Caveats

- Nothing on this page is a result. WSZ̄/OQS here are illustration arithmetic over synthetic all-zero rows.
- Arm definitions, freeze order, and the scoring contract live in [Experiment setup](../../docs/study/experiment.md) and [Measurements and scoring](../../docs/study/measurements-scoring.md); this page implements, it does not redefine.
- Snapshot refresh discipline: replace the matrix literal, re-derive every caption, and never hand-edit a derived number.
- Results, when they exist, graduate to the findings pages only after pre-freeze review; this page remains the raw audit view.

:::{dropdown} Regenerating the embedded snapshot (manual; from run results)
The cells above never touch the network and never read `results/` at build time. To replace the illustration rows with the real flattened matrix, run this recipe outside the site, then paste the printed JSON into `MATRIX_JSON` and rewrite the captions in Cells 2–5 to the printed shapes:

```bash
PYTHONPATH=experiment/src pixi run python - <<'PYEOF'
from pathlib import Path

from experiment import analyze

frame = analyze.flatten(Path("results"), Path("experiment/tasks"))
print(frame.to_json(orient="records"))
PYEOF
```

`analyze.flatten` enforces the same strict semantics the cells above implement: a run missing a named predicate's assertion scores 0, and assertions with no `predicate` mapping raise—catching YAML drift before analysis time. Re-check `print(matrix.shape)` matches `(n_runs, 5 + number of predicates)` after pasting.

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
