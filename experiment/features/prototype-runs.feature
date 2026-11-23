@cli @proto
Feature: Prototype runs and oracle scoring
  A prototype run executes each pilot task per arm and scores it with the
  oracle. It verifies the pipeline, not the study: the run is deterministic
  when the scripted driver is used, so any variation means the harness moved.

  Scenario: The tool catalogue is listed with its size
    When I run the command "proto ops"
    Then the command exits successfully
    And the output names the "relate_de9im" operation
    And the output reports the size of the operation catalogue

  Scenario: The MCP server answers a self-test
    When I run the command "proto mcp-selftest"
    Then the command exits successfully
    And the output reports the Poland–Czechia boundary relation

  Scenario: A scripted run produces one scored cell
    Given a prototype output directory
    When I run a scripted prototype for task "analysis-de9im-001" in arm "B"
    Then the command exits successfully
    And the run reports that one of one cells passed the oracle
    And the output directory holds a summary

  Scenario: An unknown driver is refused
    Given a prototype output directory
    When I run the command "proto run --driver bogus --output-dir {output}"
    Then the command fails

  Scenario: An unknown arm is refused
    Given a prototype output directory
    When I run the command "proto run --arm Q --output-dir {output}"
    Then the command fails

  Scenario: Scoring an empty directory fails rather than reporting a pass
    Given a prototype output directory
    When I run the command "proto score {output}"
    Then the command fails
    And the output says no cells were found

  Scenario: A produced run can be rescored and shown
    Given a prototype output directory
    When I run a scripted prototype for task "analysis-de9im-001" in arm "B"
    And I rescore that run
    Then the rescore reports that one of one cells passed the oracle
    And showing the run prints its oracle scores

  Scenario: Showing a directory with no summary fails
    Given a prototype output directory
    When I run the command "proto show {output}"
    Then the command fails
