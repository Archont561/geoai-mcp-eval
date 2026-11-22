# Decision: Experiment run via typer CLI app in `experiment/`

## Status

Superseded by 0006 (2026-11-22) — see
`backlog/decisions/0006-experiment-workflow.md`. The typer CLI remains the
only execution path and stays runnable locally/offline unchanged; 0006
adds manual-dispatch CI orchestration that invokes the same CLI.

## Decision

The thesis experiment will be run via a typer-based CLI app located in
`experiment/main.py`, packaged with an `experiment/pyproject.toml` and exposed
as a console script entry point. It is NOT run via tasknest tools or GitHub
Actions workflow_dispatch.

## Rationale

- tasknest's strict discovery requires every `.py` under discovery roots to
  register exactly one `@tool`, which conflicts with the experiment's modular
  layout (`run.py`, `system_prompt.py`, `hello.py`).
- GitHub Actions `workflow_dispatch` couples experiment execution to CI; a
  local typer CLI keeps the experiment runnable offline and outside CI.
- typer provides clean CLI flags (`--model`, `--task`, `--runs-per-prompt`)
  without needing environment-variable indirection.

## Changes

- Removed `.github/workflows/experiment.yml`
- Removed `tools/experiment.py` and `experiment/tools/`
- Removed `experiment/tools` discovery root from `tasknest.toml`
- Added `experiment/main.py` — typer CLI app
- Added `experiment/pyproject.toml` — references `main:app` as console script
- `pixi.toml` unchanged (experiment feature already includes `rude`,
  `rude-clean-code` from PyPI)

## Alternatives considered

- tasknest tools: rejected due to strict single-`@tool` per file discovery.
- GitHub Actions workflow_dispatch: rejected — CI coupling, no local offline
  run, env-var indirection for model/task selection.
- Raw `python -m experiment.run`: rejected — no typed CLI flags, no help text.
