# Backlog

Project-local Markdown planning managed by [Backlog.md](https://github.com/MrLesk/Backlog.md). Tasks and decisions are kept in Git alongside the experiment code; remote operations and automatic commits are disabled in `config.yml`.

## Layout

- `config.yml` — project name, task prefix, status labels, and local-first settings.
- `tasks/` — work items created with `backlog task create`.
- `milestones/` — groups related work into milestones.
- `docs/` — longer-lived project notes and plans.
- `decisions/` — architectural or research-protocol decision records.
- `drafts/` and `archive/` — drafts and completed or obsolete items.

## Use

Install the pinned tools once with `bun install --frozen-lockfile`, then use the local CLI:

```bash
bun x backlog board
bun x backlog task create
bun x backlog instructions overview
```

No task is preloaded: create backlog items after agreeing on experiment scope and priorities.
