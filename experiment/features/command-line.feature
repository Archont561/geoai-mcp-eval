@cli @smoke
Feature: Study command-line discovery and entry points
  As a GIS researcher working from a terminal
  I want every study capability to be discoverable and safe against typos
  So I can run task checks, experiments, scoring, archiving, and environment checks reliably

  Rule: Top-level help exposes every study capability group

    Scenario: Researcher views the top-level study command groups
      When I ask the study tool for top-level help
      Then the help lists the "tasks" capability group
      And the help lists the "run" capability group
      And the help lists the "score" capability group
      And the help lists the "archive" capability group
      And the help lists the "env" capability group

    Scenario: Smoke check confirms the study tool and task suite are wired together
      When I run the study smoke check
      Then the action succeeds
      And the researcher sees "smoke ok"

  Rule: Researchers can inspect setup without disclosing credentials

    Scenario: Configuration is visible without revealing a credential
      Given a configured model-service credential
      When I inspect the configuration in both display formats
      Then both displays keep the credential secret

    @edge_case
    Scenario: A missing configuration file is rejected
      Given a configuration file that does not exist
      When I inspect that configuration
      Then the action exits with status 2

    Scenario: Tool and runtime diagnostics are available for automated analysis
      Given simulated geographic tool and runtime diagnostics
      When I request machine-readable setup diagnostics
      Then the diagnostics identify the tools and available runtime

    @edge_case
    Scenario: An unavailable GIS runtime has a machine-readable verdict
      Given an environment without the GIS runtime
      When I request machine-readable GIS runtime diagnostics
      Then the diagnostics report that the runtime is unavailable

  Rule: Study configuration has predictable selection and fallback

    Scenario: A researcher selects configuration through the environment
      Given a study configuration selected in the environment
      When the researcher loads the selected configuration
      Then the configured execution driver is used

    @edge_case
    Scenario Outline: Explicitly selected missing configuration is reported
      Given a missing study configuration selected <selection>
      When the researcher loads the selected configuration
      Then the missing configuration is reported

      Examples:
        | selection                   |
        | directly                    |
        | through the environment     |

    Scenario: An absent default configuration uses built-in defaults
      Given no default study configuration file
      When the researcher loads the default configuration
      Then the built-in local model settings are used

  Rule: Unrecognized or incomplete commands fail clearly

    @edge_case
    Scenario: Unrecognized study command is rejected
      When I invoke an unknown study command
      Then the action is refused
      And the explanation identifies the unrecognized command

    @edge_case
    Scenario: Capability group invoked without an action prompts for a sub-action
      When I invoke the tasks capability group without choosing an action
      Then the action is refused
      And the explanation asks for an action
