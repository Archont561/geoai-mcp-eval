# Backlog

Project-local Markdown planning managed by [Backlog.md](https://github.com/MrLesk/Backlog.md). Tasks and decisions are kept in Git alongside the experiment code; remote operations and automatic commits are disabled in `config.yml`.

## Layout

- `config.yml` — project name, task prefix, status labels, and local-first settings.
- `tasks/` — Backlog.md work items as GEO-prefixed Markdown files; create and update them through the CLI.
- `milestones/` — groups related work into milestones (pilot, pre-freeze, v1.0-prereg, scaled-study).
- `decisions/` — architectural or research-protocol decision records.
- `docs/` — longer-lived project notes and plans, including selected documentation migrated from `docs/`; external thesis source files are not copied into this repository.
- `drafts/` and `archive/` — drafts and completed or obsolete items.

## Milestones

| Milestone | Focus |
|---|---|
| `instrument` | Harness completion: backends, usage accounting, cache, remote preflight, analysis contract (GEO-008 to GEO-012) |
| `pilot` | 3 tasks × {A@N3, B} × r=2 (GEO-001 to GEO-004) |
| `pre-freeze` | Directory hash, fixture checksums, contamination audit (GEO-005, GEO-013) |
| `v1.0-prereg` | Freeze tag + seed table (GEO-006) |
| `scaled-study` | N ≥ 80 tasks × r=4 confirmatory runs (GEO-007) |

## Project notes (selected files migrated into `backlog/docs/`)

| File | Source | Content |
|---|---|---|
| `experiment.md` | `docs/study/experiment.md` | Experiment setup: arms A/B/C/D/H, factors, task suite v1, freeze order, scoring, threats |
| `implementation.md` | `docs/study/implementation.md` | Implementation status: what exists, engineering constraints, deviations log, what appears at freeze |
| `hypotheses.md` | `docs/study/hypotheses.md` | Hypotheses & inferential contract: nulls, decision rules, multiple-comparison discipline |
| `research-questions.md` | `docs/review/research-questions.md` | Research questions: confirmatory family (gate order), secondary family, descriptive family |
| `analysis.md` | `docs/analysis.md` | SE demand analysis: operation tag counts, catalogue gaps |
| `provenance.md` | `docs/provenance.md` | Provenance: data sources, licensing, contamination tags |
| `literature-review.md` | `docs/review/literature-review.md` | Literature review: GIS canon, autonomous GIS, protocols, tool-use benchmarks |
| `gis-se-analysis.md` | `docs/analyses/gis-se-analysis.md` | GIS StackExchange demand analysis: 29 tag counts, candidate operations |

## Decisions (`backlog/decisions/`)

| File | Content |
|---|---|
| `0001-experiment-typer-cli.md` | Experiment runs via typer CLI app in `experiment/` |
| `0002-task-suite-schema-v1.md` | Task-suite YAML schema v1 (proposed) |
| `0003-model-pinning.md` | Model pinning: qwen2.5:3b primary, llama3.2:3b backup |
| `0004-enforcement-depth.md` | Enforcement depth flag (N1–N4) |
| `0005-scoring-contract.md` | Scoring contract (ISO 191157-derived predicates) |

## Use

Install the pinned tools once with `bun install --frozen-lockfile`, then use the local CLI:

```bash
bun x backlog board
bun x backlog task create
bun x backlog instructions overview
```

All tasks use the `GEO` prefix (see `backlog/config.yml`). Statuses: To Do, In Progress, Done.

Per `AGENTS.md`: manage via `bun x backlog` CLI commands, not by hand-editing tool-managed task files.
