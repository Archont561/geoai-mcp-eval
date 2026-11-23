# Experiment feature specifications

Gherkin specifications for the study CLI. Each `.feature` file here is
executable: `experiment/tests/test_cli_scenarios.py` binds every scenario to a
pytest test through pytest-bdd, and the steps drive the whole Typer application
(`experiment.cli._loader.app`, the object `python -m experiment` mounts) rather
than internal helpers.

| File | Covers |
| --- | --- |
| `command-line.feature` | command discovery, the greeting command, unknown commands |
| `pilot-suite.feature` | task-suite validation and the oracle determinism gate |
| `analysis.feature` | the flat binary predicate matrix |
| `prototype-runs.feature` | prototype runs, oracle scoring, the MCP self-test |

Adding a scenario needs no Python: write the Gherkin, then add any new step to
`experiment/tests/test_cli_scenarios.py`. Keep scenarios business-facing:
name the outcome the researcher sees, not the function that produces it.
