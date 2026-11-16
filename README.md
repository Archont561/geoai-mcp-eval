# geoai-mcp-eval

Thesis experiment code: **does the integration interface matter?** Expose nine geoprocessing operations to a pinned LLM as **typed MCP tools** versus ask the same model to **generate and run PyQGIS code** — one pinned engine, one pinned oracle, scored on executed spatial artefacts with repetitions.

> **Status: scaffold.** The repo is deliberately skeleton-only. No experiment design is pinned here, the `experiment` feature in `pixi.toml` is empty, and no GIS/AI runtime is installed. Nothing in this repo is authoritative about the study's final shape yet.

## Layout

```text
geoai-mcp-eval/
├── experiment/          # THE PYTHON SOURCE ROOT for the study (nothing else lives here yet)
├── tests/               # pytest; starts with a smoke test so the gate is never vacuous
├── tools/               # automation tasks (Tasknest, Python-native); run via `pixi run tools`
├── .github/             # CI: alint, ruff, pytest, actionlint; SHA-pinned actions
├── pixi.toml            # the ONLY environment manifest (one solve group: default)
├── tasknest.toml        # single `tools` automation entrypoint
├── AGENTS.md            # standing conventions for contributors and coding agents
└── README.md
```

**Not part of this repository by design:** the docs/site of the literature review and the thesis itself live elsewhere in the workspace (`literature/`, `baseline-thesis/`, `thesis/`). Do not recreate them here.

## Toolchain

Follows the [Archont561](https://github.com/Archont561) `*-template` toolchain, made Python-native:

- **pixi** is the only environment manager. Solve groups: `default`.
- **Tasknest (PyPI, v0.4.0)** is the task runner; **`pixi.toml` defines exactly one task** (`tools`). Everything goes through `pixi run tools …`.
- **alint** (`.alint.yml`): repo layout & policy rules — required files, hygiene, pinned actions.
- **lefthook** hooks (pre-commit, pre-push) — install once with `pixi run tools run hooks`.
- **ruff** (lint+format), **pytest** (tests), **rumdl** (Markdown), **lychee** (offline link check), **actionlint** (workflows), **vale** (prose, not part of `check`).

## Quickstart

```bash
pixi install --locked          # create the environment from the committed pixi.lock
pixi run tools ls               # list automation tasks
pixi run tools check            # alint + ruff + pytest + rumdl (the offline gate)
pixi run tools run hooks        # install pre-commit/pre-push hooks (optional)
```

> Never run environment creation inside this repo through a different package manager (`uv`, `pip install -r`, plain `python -m venv`). alint forbids stray `uv.lock`.

## CI

`.github/workflows/ci.yml` runs on pushes to `main`, PRs, and manual dispatch:

| Job          | Steps                                                        |
| ------------ | ------------------------------------------------------------ |
| `repo`       | checkout → setup-pixi (locked; `pixi.lock` is committed) → actionlint → alint → rumdl |
| `python`     | checkout → setup-pixi → ruff (check+format) → pytest         |

`pixi.lock` is committed and CI installs locked; regenerate it with `pixi lock` whenever dependencies change.

## Adding experiment dependencies

Add them to `[feature.experiment.dependencies]` (or `-pypi-dependencies`) in `pixi.toml`. If the native GIS stack grows heavy (GDAL/QGIS), give it its own solve-group — mirroring the workspace-root `pixi.toml`'s separation between the measurement solve group and tooling. Runtime dependencies never go to `pyproject.toml` (it holds tool config only).

## Honesty notes (read before trusting any of this)

Verified 2026-11-16 (pixi 0.84.2, standalone binary):

- `pixi lock` succeeds for linux-64, osx-arm64 and win-64 (see committed `pixi.lock`,
  generated 2026-11-16 with pixi 0.84.2); the solve includes the pinned PyPI tools
  (alint 0.22.1, gherlint 0.5.0, rumdl 0.3.4, tasknest 0.4.0).
- `tasknest check` and `tasknest run check` both pass (11 tasks; alint 56/56 rules;
  ruff check + format clean; pytest 1/1 with 100% coverage of `experiment/__init__.py`;
  rumdl OK after excluding `.github/` templates from Markdown lint).
- TOML/YAML all parse; `.alint.yml` verified against the real alint 0.22.1 CLI.

Not yet verified:

- `pixi install` has not been run (only `pixi lock`); the environment has not been
  created or smoke-tested. Vale/lychee/actionlint/lefthook ran only where explicitly noted.
- `pixi-sandbox` is NOT configured: it is not on conda-forge and its template channel
  answered 404 here, so the `sandbox` environment was removed (a dead env poisons every
  fresh solve). `pixi-sandbox.toml` is present but inert; re-add tool + channel together.
- `.github/workflows/ci.yml` has never run on GitHub; actions are SHA-pinned but untested
  there. The composite setup now installs locked by default.
- lefthook hooks are not installed and `lefthook.yml` is untested.
- Nothing here commits results, data, or large artifacts — keep them out of git.

## License

MIT — see `LICENSE`.
