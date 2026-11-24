@cli
Feature: The experiment command line
  Everything a researcher does from a terminal starts here: `python -m
  experiment` mounts each command group automatically, so a command that is
  not mounted is a command nobody can run.

  Scenario: The top level lists the command groups it mounted
    When I ask the command line for help
    Then the help names the "tasks" command group
    And the help names the "run" command group
    And the help names the "score" command group
    And the help names the "archive" command group
    And the help names the "env" command group

  Scenario: The smoke command verifies the CLI and task suite wiring
    When I run the command "run smoke"
    Then the command exits successfully
    And the output contains "smoke ok"

  Scenario: An unknown command is refused
    When I run the command "no-such-command"
    Then the command fails

  Scenario: A command group with no sub-command explains itself
    When I run the command "tasks"
    Then the command fails
