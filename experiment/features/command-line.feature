@cli
Feature: The experiment command line
  Everything a researcher does from a terminal starts here: `python -m
  experiment` mounts each command group automatically, so a command that is
  not mounted is a command nobody can run.

  Scenario: The top level lists the command groups it mounted
    When I ask the command line for help
    Then the help names the "analyze" command group
    And the help names the "pilot" command group
    And the help names the "proto" command group

  Scenario: A greeting is printed for a name
    When I run the command "hello hello --name world"
    Then the command exits successfully
    And the output contains "Hello, world!"

  Scenario: A greeting falls back to a default name
    When I run the command "hello hello"
    Then the command exits successfully
    And the output contains "Hello, world!"

  Scenario: An unknown command is refused
    When I run the command "no-such-command"
    Then the command fails

  Scenario: A command group with no sub-command explains itself
    When I run the command "analyze"
    Then the command fails
