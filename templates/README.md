# Repository templates

These Jinja2 (`.j2`) templates capture project-facing documentation and GitHub forms, following the template layout used by [rs-polylib-monorepo-template](https://github.com/Archont561/rs-polylib-monorepo-template/pull/1).

## Templates

- `README.md.j2` — project overview and contributor quickstart
- `AGENTS.md.j2` — contributor and coding-agent rules
- `github/ISSUE_TEMPLATE/*.j2` — issue forms and issue-form configuration
- `github/PULL_REQUEST_TEMPLATE.md.j2` — pull request checklist

The documentation templates use a `project_name` context value. The checked-in root documentation and `.github/` forms are generated snapshots; alint requires each to carry a source-template marker. A renderer and template/output parity check are not wired yet, so update the template and its checked-in output together.
