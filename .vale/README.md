# Vale style presets

The styles in `styles/` are pinned upstream releases, checked in so prose
linting works offline and produces the same results on developer machines and
in CI. `styles/config/vocabularies/Product/` contains the project vocabulary.

| Style | Version | Source | License |
| --- | --- | --- | --- |
| Microsoft | v0.15.2 | [vale-cli/Microsoft](https://github.com/vale-cli/Microsoft/tree/v0.15.2) | MIT |
| Google | v0.7.2 | [vale-cli/Google](https://github.com/vale-cli/Google/tree/v0.7.2) | MIT |
| proselint | v0.3.4 | [vale-cli/proselint](https://github.com/vale-cli/proselint/tree/v0.3.4) | BSD-3-Clause |
| write-good | v0.4.1 | [vale-cli/write-good](https://github.com/vale-cli/write-good/tree/v0.4.1) | MIT |

The upstream license texts are in `licenses/`. The original proselint and
write-good notices, supplied in their style directories as README files, are
also preserved there. The proselint and write-good versions are the latest
releases compatible with the repository's pinned Vale version.

To update a preset, replace its style directory and licenses with the files
from a tagged upstream release, update this table, and run
`pixi run tools run prose`. Review any changes in lint results before committing
the update.
