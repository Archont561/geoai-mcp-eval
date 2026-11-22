# Decision: Experiment workflow via tasknest one-liner tools wrapping the typer app

## Status

Accepted 2026-11-22 (supersedes 0001)

## Decision

The experiment is orchestrated by `.github/workflows/experiment.yml`
(manual `workflow_dispatch` only). Every shell step in the workflow is a
one-liner of the form:

```bash
pixi run tools run experiment_<verb> [options]
```

and the tasknest tools in `tools/experiment_<verb>.py` are thin, single-`@tool`
wrappers that invoke the same `experiment` typer app (`python -m experiment
<subcommand>`) that is used locally. The typer app stays the only execution
logic; the workflow adds installation-free orchestration, artifact registration,
and a `$GITHUB_STEP_SUMMARY` digest.

- Local offline runs remain first-class: `pixi run experiment …` works without
  the workflow, unchanged.
- The workflow adds only what a laptop cannot: model caching, fan-out (12-cell
  static matrix, `fail-fast: false`), `actions/upload-artifact` registration
  with retention, provenance pins (env-pins.txt, model-digest.txt), and the
  completeness assertion (harvest lists missing runs; never imputes them).

## Rationale

- 0001's concern about tasknest strict discovery was real but narrower than it
  assumed: strict single-`@tool`-per-file discovery only constrains files under
  the discovery root, and the experiment's modular typer app is untouched.
  Wrapping the app in one flat `tools/experiment_*.py` file per tool respects
  the rule rather than fights it.
- 0001's concern about CI coupling is mitigated by keeping the CLI fully
  functional locally; the workflow is optional orchestration, not the only path.
- One-liner steps are enforced repo policy (alint forbids multiline `run:`
  blocks without an ADR exemption), and they keep the workflow auditable: every
  shell action is a named, linted, `tasknest check`-validated tool.

## Changes (upon acceptance)

- `backlog/decisions/0001-experiment-typer-cli.md`: status → Superseded by 0006.
- `.github/workflows/experiment.yml`: new workflow (workflow_dispatch-only).
- `tools/experiment_preflight.py`, `tools/experiment_model.py`,
  `tools/experiment_run.py`, `tools/experiment_harvest.py`,
  `tools/experiment_summary.py`: new tools.
- `pixi.toml` unchanged; `tasknest.toml` unchanged (`tools/` discovery root,
  existing marks only).
- No change to the typer app itself.

## Alternatives considered

- Keep 0001 as-is and hand-run the experiment locally: rejected by explicit
  direction to orchestrate in GitHub Actions.
- Workflow calls the typer app directly (no tasknest): rejected — violates the
  repo's `pixi run tools run <name>` automation entrypoint convention and alint
  policy against multiline run blocks.
- tasknest discovery root inside `experiment/`: rejected — 0001's discovery
  concern applies there; flat `tools/` wrappers avoid it.

## Open items

- Acceptance: human sign-off required before experiment execution in CI is
  treated as sanctioned; the workflow is manual-dispatch-only until then.
- The `pilot` stage of `experiment_run` fails loudly until the agent harness
  (Stage 2: MCP catalogue, codegen executor, runner) lands; smoke stage is for
  pipeline verification only and is not a study result.
