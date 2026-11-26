<!-- Generated from templates/README.md.j2; do not edit directly. -->

# geoai-mcp-eval

Thesis experiment code: **does the integration interface matter?** Expose geoprocessing operations to a pinned LLM as **typed MCP tools** versus ask the same model to **generate and run PyQGIS code**: one engine, one oracle, scored on executed spatial artefacts.

> **Status: pre-experiment.** The repository contains a Typer experiment CLI and a QGIS plugin prototype. The protocol isn't frozen, no confirmatory runs have been made, and nothing here is a study result. The preregistration tag `v1.0-prereg` is the intended freeze point.

## Study terminology

- A **treatment** specifies an approach and enforcement settings, independent of the task.
- A **condition** combines one task with one treatment.
- A **trial** is one execution of a condition; repeated trials have different repetition numbers.
- A **run** is a batch of trials. Analysis tables aggregate trials by condition.

Legacy names such as `cell`, `cells`, and `max_cell_tokens` remain in stored records,
configuration, APIs, and artifact paths for compatibility. The CLI accepts the old
`run cell` and `--max-cell-tokens` spellings alongside `run trial` and
`--max-trial-tokens`; existing archives and automation need no migration.

## Layout

```text
geoai-mcp-eval/
├── experiment/
│   ├── src/experiment/  # study CLI and reusable experiment code
│   ├── features/        # executable Gherkin specifications for the CLI
│   └── tests/           # experiment CLI tests and the scenario steps
├── experiment-qgis-plugin/
│   ├── experiment_plugin/  # qgis-sdk plugin prototype (flat layout)
│   ├── features/        # executable Gherkin specifications for the plugin
│   └── tests/           # plugin tests and the scenario steps
├── docs/                # pre-experiment MyST documentation book
├── .agents/skills/      # upstream and repository-maintained agent skills
├── backlog/             # local-first tasks, milestones, decisions, and plans
├── templates/           # Jinja2 sources for generated docs and GitHub forms
├── tools/               # Tasknest automation; run via `pixi run tools`
├── pixi.toml            # Pixi workspace and environments
├── package.json         # pinned Bun CLIs (skills and Backlog.md only)
├── bun.lock             # Bun dependency lock
├── skills-lock.json     # upstream agent-skill source pins and hashes
├── tasknest.toml        # Tasknest automation configuration
├── AGENTS.md            # standing contributor and agent conventions
└── README.md
```

The documentation book presents a proposed design and public-source context, not a frozen protocol. Findings pages are intentionally marked ToDo. The GIS Stack Exchange snapshot in the analysis pages has an unverified retrieval date and values; validate them against the source before relying on them. The canonical thesis and literature review remain outside this repository.

## Toolchain

- **Pixi** is the Python environment manager. Package-level `pyproject.toml` files describe the CLI and plugin; Pixi resolves workspace environments.
- **Tasknest** is the sole repository automation entry point (`tools`). `pixi.toml` also exposes `experiment` as the experiment CLI task, not as repository automation.
- **Ruff**, **pytest**, **rumdl**, **Vale**, **alint**, **actionlint**, and **lychee** provide linting, tests, and repository checks.
- Experiment coverage targets `experiment/`; pytest and Codecov enforce the configured 90% threshold.
- Behaviour is specified in `.feature` files under `experiment/features/` and `experiment-qgis-plugin/features/`. pytest-bdd binds each scenario to a test, so the feature files run; they're specifications, not notes.
- The `docs` environment has a separate solve group for MyST and reactive analysis dependencies. The optional sandbox environment installs `pixi-sandbox` from the `https://prefix.dev/archont561/archont561` channel and `qgis` from conda-forge; both resolved when the sandbox environment was last installed on linux-64, but the QGIS Desktop session itself isn't exercised by CI.

## Quickstart

```bash
pixi install --locked
pixi run tools ls                 # list repository automation tasks
pixi run tools check              # alint + ruff + pytest + rumdl
pixi run experiment --help        # experiment CLI
pixi run tools run prose          # Vale technical/scientific prose checks
pixi run tools run hooks          # install hooks (optional)
```

Never create a Python environment in this repository with another package manager (`uv`, `pip install -r`, or plain `python -m venv`).

## Agent skills and backlog

Bun is used only to pin the agent-skill and Backlog.md CLIs; Pixi remains the Python environment manager. Install the CLIs with the committed lockfile, then restore project skills or use the backlog:

```bash
bun install --frozen-lockfile
bun x skills experimental_install --frozen-lockfile
bun x skills list
bun x backlog board
```

Five upstream skills are copied to `.agents/skills/` and locked in `skills-lock.json`; the repository-maintained `code-review` skill lives alongside them. Backlog.md stores tasks, milestones, decisions, and project notes under `backlog/`; its settings disable remote operations and automatic commits. Use `bun x backlog task create` to add work items.

## CI and documentation

CI runs repository policies, Markdown and prose checks, Python lint/tests, and builds the MyST site from `docs/myst.yml`. Pages deploy on pushes to `main`. The Pages workflow also checks generated sitemap and LLM text artifacts.

`pixi.lock` is committed; regenerate it with `pixi lock` whenever Pixi dependencies change. The `pixi-sandbox.toml` bundle publishes all four environments to the `sandbox/developer-linux-64` branch through `.github/workflows/publish-sandbox.yml`; restore a machine from that branch with `./restore.sh` (`PIXI_SANDBOX_BUNDLE` selects a bundle when several share a platform). The publisher needs `contents: write`; it's the only workflow allowed to hold it.

## Scope and provenance

The study design remains open until preregistration. Keep documentation focused on the pre-experiment book; don't add the canonical thesis or literature review here. Public GIS Stack Exchange material is CC BY-SA 4.0 and must retain attribution and provenance. Don't commit private data, unpublished run outputs, or GIS binaries.

## License

MIT—see `LICENSE` for the code scaffold. Public-source material carries its own attribution and license as documented on the site.
