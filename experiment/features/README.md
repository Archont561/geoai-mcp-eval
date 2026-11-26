# Experiment feature specifications

These executable specifications describe the study from the researcher's
perspective. The bindings in `experiment/tests/` use pytest-bdd to exercise the
study tool and analysis code.

| Feature | Coverage |
| --- | --- |
| `command-line.feature` | Command discovery and safe handling of invalid commands |
| `pilot-suite.feature` | Task discovery, result formats, machine-readable reports, validation, and repeated oracle checks |
| `oracle-grading.feature` | Determinism checks and unreliable grading verdicts |
| `prototype-runs.feature` | Prototype runs, scoring, token budgets, and caching |
| `experiment-runs.feature` | Model preparation, tool sessions, and experiment cells with response reuse |
| `qgis-sandbox.feature` | GIS runtime availability, version reports, and isolated script execution |
| `workflow.feature` | Research workflow from task validation to archive |
| `run-archives.feature` | Archive packing, inspection, integrity, and missing trial evidence |
| `backend-preflight.feature` | Model service configuration, readiness, connection failures, and retry policy |
| `analysis-dataset.feature` | Analysis tables, local archives, and safe remote retrieval |

Follow the [BDD scenario skill](../../.agents/skills/bdd-scenarios/SKILL.md)
when adding a feature. Describe observable domain outcomes rather than code or
command flags. Group acceptance criteria under rules, keep scenarios independent
and focused, and bind every scenario to executable steps. The architecture gate
checks that pytest collects each scenario, that every pure domain module has
at least one mirrored Hypothesis property test, and that every test in the pure
domain test suite is a Hypothesis property. It also requires every other test in
the experiment and plugin suites to be either a bound BDD scenario or a
Hypothesis property, apart from smoke tests and architecture/quality gates.

Each scenario should contain three to seven steps of its own; shared background
setup is excluded from that count. The gate checks this and requires a rule
for each scenario. For adapter, CLI, service, and plugin modules, it also checks
a mirrored property module or an explicit feature mapping. The property check
rejects tests whose only generated inputs are fixed values, but automated checks
can't establish that a property is meaningful or that a feature preserves every
previous behavioral assertion; reviewers must check both.
