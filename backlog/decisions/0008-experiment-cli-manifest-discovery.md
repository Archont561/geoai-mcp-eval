# Decision: Experiment workflow commands in the experiment CLI, discovered by Tasknest via manifest

## Status

Accepted 2026-11-24 (supersedes 0006)

## Decision

All experiment workflow commands (`preflight`, `model`, `run`, `harvest`,
`summary`, and `backend-check`) live inside the `experiment` package
(`experiment.services.workflow`, `experiment.services.workflow_summary`,
`experiment.services.backend_check`, and `experiment.cli.workflow`, mounted as
`experiment workflow <command>`), rather than as standalone Python scripts under
root `tools/`.

Tasknest resolves these commands via Tier-1 manifest autodiscovery:

- `tasknest.toml` registers `[[discovery.manifests]]` with `path = "experiment"`.
- `experiment/pyproject.toml` declares `[tool.tasknest.tasks.<name>]` entries
  for `preflight`, `model`, `run`, `harvest`, `summary`, and `backend-check`
  using explicit argv arrays targeting `experiment workflow <name>`.
- Every `experiment workflow` option accepts both explicit CLI flags (for direct
  local execution via `pixi run experiment workflow <name> ...`) and environment
  variables (so flag-free `pixi run tools run experiment <name>` calls work in
  CI and locally).
- Root `tools/` contains only repository-wide automation (`check`, `lint`,
  `test`, `md`, `alint`, `architecture`, etc.).

## Rationale

- Keeping experiment workflow logic inside `experiment/src/experiment/` brings
  it under the package's `import-linter` architecture contracts, pytest
  coverage reporting, and Typer CLI surface — eliminating duplicated `tools/`
  plumbing (`_experiment_common.py` and six `tools/experiment_*.py` wrappers).
- Tasknest's Tier-1 manifest discovery (`[[discovery.manifests]]` +
  `[tool.tasknest.tasks]` in `pyproject.toml`) preserves a single automation
  entrypoint (`pixi run tools run experiment <verb>` and `pixi run tools ls -p
  experiment`) with zero boilerplate wrapper files.
- `.github/workflows/experiment.yml` continues to run single-line
  `pixi run tools run experiment <verb>` steps, passing matrix/input parameters
  cleanly through `env:` bindings.

## Consequences

- `tools/_experiment_common.py` and `tools/experiment_*.py` are removed.
- `.agents/skills/project-tools/SKILL.md` is regenerated via `pixi run tools
  skill --write` and lists the manifest-discovered `experiment <verb>` tasks.
- Any future experiment sub-package can opt into Tasknest discovery simply by
  declaring `[tool.tasknest.tasks]` in its `pyproject.toml`.
