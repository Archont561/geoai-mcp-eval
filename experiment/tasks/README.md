# Pilot task suite (schema v1 draft)

This is a **prepared, not frozen or executed** pilot suite. It contains one P (prepare/IO), one A (analysis), and one C (cartography) task. All three use compact extracts of Natural Earth Vector's 1:110m Admin 0 Countries layer; the tasks and fixture extracts are author-constructed from that public source. The pilot validator enforces its three task-specific acceptance traps (CRS/axis order, topology/DE-9IM, and Jenks/classification). Raster, zonation/MAUP, and NoData traps belong to the proposed expanded suite and are **not** represented as covered by these three pilot tasks; they must be added and verified before any broader-suite freeze.

## Source and provenance

- Dataset: [Natural Earth Vector](https://github.com/nvkelso/natural-earth-vector), `geojson/ne_110m_admin_0_countries.geojson`.
- Source commit: `ca96624a56bd078437bca8184e78163e5039ad19`.
- The upstream repository README describes Natural Earth as a public-domain dataset. GitHub's repository-level license field is `NOASSERTION`; the README statement is the provenance basis used here, not a legal opinion. Preserve this attribution and verify the intended licensing treatment before publication.
- SHA-256 of the unmodified upstream GeoJSON: `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.
- The committed fixtures contain only the features/properties needed for the tasks. No GIS Stack Exchange prompt is inherited.

| Task | Fixture | SHA-256 | Trap |
|---|---|---|---|
| `prep-axis-order-001` | `fixtures/prepare/poland.geojson` | `27b2a0f2abdcf5a32f0146a32a62bca4c490c3d19057a6a054acd4abe17dc869` | CRS / longitude-latitude axis order |
| `analysis-de9im-001` | `fixtures/analysis/poland-czechia.geojson` | `92ce1499bf8a5b18cdcc6e778f78193521f8ed3b4e997b99460e98d8a761c610` | DE-9IM shared boundary |
| `cartography-jenks-001` | `fixtures/cartography/countries.geojson` | `fc04824a8311e3cf4f4785e2f0fbb9e18ede046ac6b51cead56a75f8e47e79e1` | Fisher–Jenks classification |

## Validate and run the determinism gate

```bash
pixi run experiment pilot validate
pixi run experiment pilot determinism prep-axis-order-001 --artifacts-dir /path/to/prep-axis-order-001
```

Each task expects a separate artifact directory containing the output file named in its oracle assertions. The determinism command evaluates the same fixed artefacts three times. Missing artefacts, inconsistent verdicts, or oracle errors fail with a per-run report. The gate tests oracle repeatability; it does not execute an agent arm or constitute pilot study results.

## Human reference H — user execution pending

Do not mark any `human_baseline.status` complete or run agent comparisons until the task suite and oracle have been reviewed and frozen. When authorized, an analyst should:

1. Use the exact task prompt and fixture, in a clean QGIS profile, with network access disabled.
2. Save the requested output under the task's `human_baseline.artifact_dir`; record QGIS version, processing log, elapsed minutes, steps, and tools in a machine-readable run record.
3. Run the same three-pass oracle gate against that artifact and preserve the report.
4. Capture a screen recording only with the participant's consent. Keep raw recordings, profiles, and any potentially identifying material outside Git in approved private storage; commit only a reviewed, sanitized record.
5. Report H descriptively, only after agent-run analysis is locked. It is a reference, not a baseline to beat.

The baseline and run-artifact directories are gitignored. No human session, agent run, or baseline output is included in this prepared suite.
