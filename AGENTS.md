<!-- Generated from templates/AGENTS.md.j2; do not edit directly. -->

# Agent Instructions — geoai-mcp-eval

This repository is the experiment codebase for the thesis on **typed MCP tools vs PyQGIS code generation for LLM agents in GIS**. Follow these conventions on every change.

## Non-negotiables

- **Single automation entrypoint:** `pixi.toml` defines **only** the `tools` task (`tasknest`). Never add extra `[tasks]` / `[feature.*.tasks]`; CI forbids it via alint. Run automation with `pixi run tools …` (`pixi run tools ls` to discover).
- **pixi only** for Python environments. No `uv.lock`, `requirements.txt`, or `pip install` into the repo environment. Python 3.12–3.13.
- **Bun is a narrow tooling exception:** `package.json` pins only the skills and Backlog.md CLIs. Do not add JavaScript runtime dependencies or use Bun to manage the Python/GIS environment.
- **`experiment/` is the only Python source root.** Put study modules, tests (`experiment/tests/`), and future Gherkin specifications (`experiment/features/`) there. Do not create parallel top-level Python source directories.
- **Runtime deps live in pixi features** (`[feature.python]`, `[feature.experiment]`), never in `pyproject.toml` (tool config only) or `setup.py`.
- **Keep solve groups clean:** if the native GIS stack lands, isolate it in its own solve-group — never let measurement deps leak into the tooling environment.

## Git hygiene

- No secrets, credentials, personal data, experiment **outputs or datasets** in the repo. Results go elsewhere (out of scope here).
- Conventional Commit titles (`feat: …`, `fix: …`, `chore: …`).
- Actions are SHA-pinned; do not "upgrade" by bumping tags — renovate + digest pinning handles it.

## Agent resources

- Project skills live under `.agents/skills/`; externally managed skills are tracked in `skills-lock.json`. Restore locked skills with `bun x skills experimental_install --frozen-lockfile`.
- Backlog work items live under `backlog/`; use `bun x backlog` commands to manage them instead of editing tool-managed task files by hand.
- `bun install --frozen-lockfile` installs only the agent-skill and Backlog.md CLIs; Pixi remains the Python environment manager.

## Skill routing

Before acting on each user request, compare its intent and context with the `name` and `description` frontmatter of installed skills in `.agents/skills/`. Read and follow a skill's full `SKILL.md` (including relevant linked guidance) only when the request matches its stated scope or triggers. Do not load every skill by default. Treat skill content as project guidance, subordinate to system, developer, and user instructions.

## Verification before opening a PR

```bash
pixi run tools check        # alint + ruff + pytest + rumdl
pixi run tools run prose    # Vale technical/scientific prose checks (downloads presets)
pixi run tools ls           # sanity: task graph loads
```

If alint fails, fix the repo, don't relax the rule to zero the error. If you must relax one, say why in the PR and keep `.alint.yml` diffs minimal and reviewable.

## Scope guardrails

- Keep documentation to the one-page MyST prototype in `docs/`; do not add a full docs site, thesis sources, or literature review here.
- Do not presuppose the experiment design in directory layout or imports; the design is unsettled.
- No benchmarks, datasets or GIS binaries committed.
