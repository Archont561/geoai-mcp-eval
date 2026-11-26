# Plugin behaviour specifications

These executable specifications describe the QGIS plugin from the participant's
and reviewer's perspectives. The scenario modules in `tests/` bind the features
through pytest-bdd; `tests/plugin_harness.py` supplies QGIS and Qt doubles.

| Feature | Coverage |
| --- | --- |
| `hello.feature` | Plugin action surface and lifecycle |
| `human-baseline.feature` | Session recording and human-baseline evidence |
| `session-panel.feature` | Session controls, timer, and log export |
| `host-observation.feature` | Observing project, canvas, and processing activity |
| `post-session-review.feature` | Reviewing recorded sessions without changing raw evidence |

Follow the [BDD scenario skill](../../.agents/skills/bdd-scenarios/SKILL.md)
when adding scenarios: use domain language, group acceptance criteria under
rules, keep scenarios independent and focused, and bind them to executable
steps. The architecture gate also checks that scenarios are bound and that
non-BDD tests use Hypothesis properties, apart from the structural and smoke gates.
