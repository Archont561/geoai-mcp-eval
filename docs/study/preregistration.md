---
title: Preregistration checklist
short_title: Preregistration
description: >-
  Preregistration checklist (what will live in Appendix E) from the frozen thesis
  specification: document + YAML checksums, oracle details, run protocol, stopping
  rules, analysis scripts pinned.
---

(fresh-prereg)=

# Preregistration checklist

**Status:** pre-implementation design specification (post-professor-consultation).

---

## What will live in Appendix E

- This document + YAML checksums; arm prompt scaffolds verbatim; catalogue JSON +
  hash; N-flag semantics (exact check order: syntax → enum/units → domain →
  postcondition).
- Oracle: assertion IDs, types, tolerances; third-party-checker versions;
  3× determinism evidence.
- Run protocol: randomisation list hash; session-freshness rule; logging schema
  (`results.jsonl` fields: `run_id, task_id, arm, N, stratum, seed?, model_id,
  date, driver, prompt_hash, artefact_path, artefact_sha256, tool_calls, repairs,
  assertions[], WSZ, OQS, wall_s, tokens?`); failure-class rubric with κ target.
- Stopping rules: oracle instability or log loss ≥ 1 % → stop, report instrument
  failure (not model failure).
- Analysis scripts pinned; alpha .05; correction family pre-named.

## Scope clarification (pre-freeze, 2026-11-22)

The confirmatory interface contrast is carried by the A and P families; the C
(Jenks) task is a pre-registered descriptive counter-case and never gates WSZ.
No visualization or cartographic-quality outcome enters pass/fail scoring; such
outcomes remain descriptive (F-family) only, by judgement and never by oracle.

## Addendum — arm B prompt scaffold tightened (pre-freeze, 2026-11-22)

Before Appendix E freezes the scaffolds verbatim, the arm B system prompt was
corrected: it instructed the model to "Print the deliverable … to stdout"
without requiring a ```python fenced block, while the harness executes only
```python fences — so a compliant model that answered with a ```json block (as
the task text suggests) was scored as failing, measuring instruction
contradiction rather than code-generation ability. The frozen text therefore
reads: "Reply with ONLY a single ```python fenced code block containing the
complete script; no prose and no other fences. The script must print the
deliverable … to stdout". No other part of either scaffold changed; arm A was
left untouched. Verified pre-freeze with the local 0.5B coding model and
recorded below with the study pin on the GitHub Actions runner (`GEO-011`).

### Frozen arm B system prompt (ratified 2026-11-24)

- **Source:** `experiment/src/experiment/domain/prompts.py` (`ARM_B_SYSTEM_PROMPT`)
- **Length:** 418 bytes (UTF-8)
- **SHA-256:** `5c44378126c5b889a159b7524ea83bf0d365f45854ee2559b38230851ac1c985`

```text
You solve one GIS task by writing a Python script. Use only the standard library plus geopandas/shapely/pyproj. The fixture is available as 'input.geojson' in the working directory. Reply with ONLY a single ```python fenced code block containing the complete script; no prose and no other fences. The script must print the deliverable (result.json or result.geojson) as a single JSON object to stdout and nothing else.
```

### Pre-freeze evidence — 0.5B coding model (`qwen2.5-coder:0.5b`, 2026-11-24)

- **Workflow run:** GitHub Actions `experiment.yml` (`stage=pilot`), Run
  `#45505815319` (`commit 4a7efe5b2742dfa175e7c3581acc994cb41305a2`)
- **Model pin:** `qwen2.5-coder:0.5b`, digest
  `4ff64a7f502a08b7616edb8ca0a79eb1853fc363d842b7df4b46915d11a3fb09`
- **Environment:** Python `3.13.18`, QGIS `4.2.3-Belém do Pará`
- **Archive bundle:**
  `experiment-run-45505815319-4a7efe5b2742dfa175e7c3581acc994cb41305a2`
  (artifact ID `14972624264`, 169,754 bytes; contains verbatim `score.json` and
  `transcript.jsonl` for all 12 pilot cells; 3× oracle determinism gate passed)

| Task | Rep | Python fence | Script exit | TSR | MPS | Silent invalid | Tokens | Wall (s) | Verbatim outcome |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| `analysis-de9im-001` | 1 | No | — | 0 | 0.00 | No | 2,121 | 18.69 | Emitted `` ```json `` (`{"relation": "touches", "de9im": "Czechia touches Poland"}`); harness logged `no python block found`. |
| `analysis-de9im-001` | 2 | No | — | 0 | 0.00 | No | 2,120 | 8.70 | Emitted `` ```json `` (`{"relation": "touches", "de9im": "2297"}`); harness logged `no python block found`. |
| `cartography-jenks-001` | 1 | No | — | 0 | 0.00 | No | 4,098 | 88.23 | Prose description of fixture features (8,378 chars); harness logged `no python block found`. |
| `cartography-jenks-001` | 2 | Yes | 1 | 0 | 0.00 | No | 2,304 | 16.83 | Prose + Python fence; script exited 1 (`FileNotFoundError` opening hardcoded `'countries.geojson'`). |
| `prep-axis-order-001` | 1 | No | — | 0 | 0.00 | No | 2,345 | 48.59 | Emitted raw `` ```json `` `FeatureCollection` (1,396 chars); harness logged `no python block found`. |
| `prep-axis-order-001` | 2 | No | — | 0 | 0.00 | No | 2,345 | 42.63 | Emitted raw `` ```json `` `FeatureCollection` (1,396 chars); harness logged `no python block found`. |

**Summary (`qwen2.5-coder:0.5b`, Arm B):** Python fence emitted in `1/6` cells;
TSR `0/6` (`0.00%`); mean predicate score `0.0000`; silent-invalid `0/6`. (Arm
A reference in the same run: TSR `0/6`, MPS `0.0000`, silent-invalid `2/6` on
`analysis-de9im-001` reps 1–2.)

### Pre-freeze evidence — study pin (`qwen2.5:3b`, 2026-11-24)

- **Workflow run:** GitHub Actions `experiment.yml` (`stage=pilot`), Run
  `#45505826575` (`commit 4a7efe5b2742dfa175e7c3581acc994cb41305a2`)
- **Model pin:** `qwen2.5:3b`, digest
  `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`
- **Environment:** Python `3.13.18`, QGIS `4.2.3-Belém do Pará`
- **Archive bundle:**
  `experiment-run-45505826575-4a7efe5b2742dfa175e7c3581acc994cb41305a2`
  (artifact ID `14974065703`, 172,083 bytes; contains verbatim `score.json` and
  `transcript.jsonl` for all 12 pilot cells; 3× oracle determinism gate passed)

| Task | Rep | Python fence | Script exit | TSR | MPS | Silent invalid | Tokens | Wall (s) | Verbatim outcome |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| `analysis-de9im-001` | 1 | Yes | 1 | 0 | 0.00 | No | 2,373 | 107.09 | Emitted `geopandas`/`shapely`/`pyproj` script (990 chars); exited 1 (`ERROR 1: PROJ: proj_create_from_database: Open of .../share/proj failed` + traceback); `shared-boundary-relation` failed (missing `result.json`). |
| `analysis-de9im-001` | 2 | Yes | 1 | 0 | 0.00 | No | 2,284 | 102.16 | Emitted `geopandas`/`shapely` script (754 chars); exited 1 (`ERROR 1: PROJ: proj_create_from_database: Open of .../share/proj failed` + traceback); `shared-boundary-relation` failed (missing `result.json`). |
| `cartography-jenks-001` | 1 | No | — | 0 | 0.00 | No | 2,394 | 75.14 | Prose description of fixture features (1,546 chars); harness logged `no python block found`; `natural-breaks-assignments` failed. |
| `cartography-jenks-001` | 2 | No | — | 0 | 0.00 | No | 2,368 | 66.31 | Prose description of fixture features (1,394 chars); harness logged `no python block found`; `natural-breaks-assignments` failed. |
| `prep-axis-order-001` | 1 | Yes | 0 | 0 | 0.50 | Yes | 1,506 | 44.69 | Emitted `geopandas`/`shapely` script (852 chars); exited 0 and printed valid GeoJSON `FeatureCollection` to stdout (with `PROJ` warning on stderr). Oracle: `single-output-feature` **passed** (`feature count 1; expected 1`), `representative-point-axis-order` **failed** (`output geometry must be a GeoJSON Point`). |
| `prep-axis-order-001` | 2 | Yes | 1 | 0 | 0.00 | No | 1,492 | 47.55 | Emitted `geopandas`/`shapely` script (846 chars); exited 1 (`ERROR 1: PROJ: proj_create_from_database: Open of .../share/proj failed` + traceback); both assertions failed (missing `result.geojson`). |

**Summary (`qwen2.5:3b`, Arm B):** Python fence emitted in `4/6` cells overall
(`4/4` on confirmatory A and P families; `0/2` on descriptive C-family
`cartography-jenks-001`); TSR `0/6` (`0.00%`); mean predicate score `0.0833`
(`0.5000` on `prep-axis-order-001` rep 1); silent-invalid `1/6`. (Arm A
reference in the same run: TSR `0/6`, MPS `0.0000`, silent-invalid `2/6` on
`analysis-de9im-001` reps 1–2.)

#### Verbatim runner evidence (`qwen2.5:3b`, Harvest check-run notices)

```json
{
  "run_id": "45505826575-4a7efe5b2742dfa175e7c3581acc994cb41305a2",
  "model": "qwen2.5:3b",
  "digest": "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b",
  "codegen": [
    {
      "id": "analysis-de9im-001/codegen/none/rep-1",
      "ok": false,
      "mps": 0.0,
      "wall_s": 107.09,
      "tok": 2373,
      "fence": true,
      "rc": 1,
      "reply_len": 990,
      "reply_head": "```python\nimport geopandas as gpd\nfrom shapely.ops import unary_union\nfrom pyproj import CRS\n\n# Read the GeoJSON file\ngdf = gpd.read_file(\"input.geojson\")\n\n# Define the CRS\ncrs = CRS.from_epsg(4326)\n\n# Convert GeoDataFra",
      "stderr_head": "ERROR 1: PROJ: proj_create_from_database: Open of /home/runner/work/geoai-mcp-eval/geoai-mcp-eval/.pixi/envs/default/share/proj failed\nTrace",
      "assertions": [{"id": "shared-boundary-relation", "ok": false}]
    },
    {
      "id": "analysis-de9im-001/codegen/none/rep-2",
      "ok": false,
      "mps": 0.0,
      "wall_s": 102.16,
      "tok": 2284,
      "fence": true,
      "rc": 1,
      "reply_len": 754,
      "reply_head": "```python\nimport geopandas as gpd\nfrom shapely.ops import unary_union\nimport json\n\n# Load the GeoJSON file\ngdf = gpd.GeoDataFrame.from_file(\"input.geojson\")\n\n# Union the geometries to get single polygons\nunioned = unary_",
      "stderr_head": "ERROR 1: PROJ: proj_create_from_database: Open of /home/runner/work/geoai-mcp-eval/geoai-mcp-eval/.pixi/envs/default/share/proj failed\nTrace",
      "assertions": [{"id": "shared-boundary-relation", "ok": false}]
    },
    {
      "id": "cartography-jenks-001/codegen/none/rep-1",
      "ok": false,
      "mps": 0.0,
      "wall_s": 75.14,
      "tok": 2394,
      "fence": false,
      "rc": null,
      "reply_len": 1546,
      "reply_head": "It appears that you've provided a JSON-like structure containing multiple geographical features, specifically countries and their geometries. This data seems to be structured for use with mapping and geographic informati",
      "assertions": [{"id": "natural-breaks-assignments", "ok": false}]
    },
    {
      "id": "cartography-jenks-001/codegen/none/rep-2",
      "ok": false,
      "mps": 0.0,
      "wall_s": 66.31,
      "tok": 2368,
      "fence": false,
      "rc": null,
      "reply_len": 1394,
      "reply_head": "It appears that you've provided a JSON structure containing multiple geographical features, specifically countries and their geometries. This data seems to be intended for a mapping application or GIS system. Here's a br",
      "assertions": [{"id": "natural-breaks-assignments", "ok": false}]
    },
    {
      "id": "prep-axis-order-001/codegen/none/rep-1",
      "ok": false,
      "mps": 0.5,
      "wall_s": 44.69,
      "tok": 1506,
      "fence": true,
      "rc": 0,
      "reply_len": 852,
      "reply_head": "```python\nimport geopandas as gpd\nfrom shapely.geometry import Point\nimport json\n\n# Read the GeoJSON file\ngdf = gpd.GeoDataFrame.from_file('input.geojson')\n\n# Select the feature with ISO_A3 property 'POL'\nfeature = gdf[g",
      "stdout_head": "{\"type\": \"FeatureCollection\", \"name\": \"result\", \"crs\": {\"type\": \"name\", \"properties\": {\"name\": \"urn:ogc:def:crs:OGC:1.3:CRS84\"}}, \"features\"",
      "stderr_head": "ERROR 1: PROJ: proj_create_from_database: Open of /home/runner/work/geoai-mcp-eval/geoai-mcp-eval/.pixi/envs/default/share/proj failed\n",
      "assertions": [
        {"id": "single-output-feature", "ok": true, "d": "feature count 1; expected 1"},
        {"id": "representative-point-axis-order", "ok": false, "d": "output geometry must be a GeoJSON Point"}
      ]
    },
    {
      "id": "prep-axis-order-001/codegen/none/rep-2",
      "ok": false,
      "mps": 0.0,
      "wall_s": 47.55,
      "tok": 1492,
      "fence": true,
      "rc": 1,
      "reply_len": 846,
      "reply_head": "```python\nimport geopandas as gpd\nfrom shapely.geometry import Point\nimport json\n\n# Read the GeoJSON file\ngdf = gpd.GeoDataFrame.from_file(\"input.geojson\")\n\n# Select the feature with ISO_A3 property 'POL'\nfeature = gdf[g",
      "stderr_head": "ERROR 1: PROJ: proj_create_from_database: Open of /home/runner/work/geoai-mcp-eval/geoai-mcp-eval/.pixi/envs/default/share/proj failed\nTrace",
      "assertions": [
        {"id": "single-output-feature", "ok": false},
        {"id": "representative-point-axis-order", "ok": false}
      ]
    }
  ]
}
```

#### Ratification ruling (2026-11-24)

1. The tightened Arm B prompt scaffold (`5c443781…`) is ratified as frozen for
   Appendix E without further prompt or harness edits.
2. On confirmatory tasks (`analysis-de9im-001`, `prep-axis-order-001`), the
   study pin `qwen2.5:3b` reliably emitted `` ```python `` blocks (`4/4` cells),
   whereas on the descriptive C-family counter-case (`cartography-jenks-001`) it
   emitted prose without a code fence (`0/2` cells). This non-fence outcome is
   recorded verbatim rather than patched post-hoc.
3. All four executed `qwen2.5:3b` scripts logged a `PROJ` database path error on
   `stderr` inside the sandboxed Python subprocess; no harness patch accompanies
   this ratification. Any future sandbox environment change before `v1.0-prereg`
   must be documented in a separate dated pre-freeze addendum.

## Addendum — arm B sandbox isolation & PROJ/GDAL data paths (pre-freeze, 2026-11-25)

Before tagging `v1.0-prereg`, two environment-level harness fixes were applied
to Arm B's Python execution sandbox (`experiment/src/experiment/adapters/harness_io.py`):

1. **Ephemeral temporary working directory (`4f56747`):** Each Arm B script
   now executes inside a fresh `tempfile.TemporaryDirectory(prefix="geoai-sandbox-")`
   containing only a copy of the task fixture staged at relative path
   `input.geojson`, rather than executing inside the cell's output directory.
   The temporary directory and any scratch files are deleted automatically on
   exit, isolating generated scripts from `transcript.jsonl`, `score.json`, and
   `manifest.json`.
2. **Read-only `PROJ`/`GDAL` data paths in `scrubbed_env()`:** In the
   2026-11-24 study-pin pilot (`#45505826575`), stripping `PROJ_DATA` caused
   every `geopandas`/`pyproj` script to log
   `ERROR 1: PROJ: proj_create_from_database: Open of .../share/proj failed`
   while Arm A's MCP server inherited working `PROJ`/`GDAL` paths. To preserve
   interface fairness without exposing host secrets or network access,
   `scrubbed_env()` now forwards only an explicit read-only allowlist resolved
   from the active interpreter prefix (`PROJ_DATA`, `GDAL_DATA`,
   `GDAL_DRIVER_PATH`) and pins `PROJ_NETWORK=OFF`.

Neither Arm A nor Arm B system prompts changed (`ARM_B_SYSTEM_PROMPT` SHA-256
remains `5c44378126c5b889a159b7524ea83bf0d365f45854ee2559b38230851ac1c985`).
