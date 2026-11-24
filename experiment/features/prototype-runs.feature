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
    And the output reports the tool count and the filtered Poland feature
    And the output reports the Poland–Czechia boundary relation

  Scenario: A scripted run produces one scored cell
    Given a prototype output directory
    When I run a scripted prototype for task "analysis-de9im-001" in arm "B"
    Then the command exits successfully
    And the run reports that one of one cells passed the oracle
    And the output directory holds a summary
    And the output warns that this is not a study result

  Scenario: An unknown driver is refused
    Given a prototype output directory
    When I run the command "proto run --driver bogus --output-dir {output}"
    Then the command exits with code 2
    And the output contains "--driver must be one of scripted, ollama"
    And no output directory is created

  Scenario: An unknown arm is refused
    Given a prototype output directory
    When I run the command "proto run --arm Q --output-dir {output}"
    Then the command exits with code 2
    And the output contains "--arm must be one of both|A|B, got 'Q'"
    And no output directory is created

  Scenario: An unknown backend is refused
    Given a prototype output directory
    When I run the command "proto run --backend bogus --output-dir {output}"
    Then the command exits with code 2
    And the output contains "config: unknown backend 'bogus'"
    And no output directory is created

  Scenario: A hosted backend without its key is refused before a run starts
    Given a prototype output directory
    And the hosted backend has no API key
    When I run the command "proto run --driver ollama --backend free-open --output-dir {output}"
    Then the command exits with code 2
    And the output contains "environment variable OPENROUTER_API_KEY is unset"
    And no output directory is created

  Scenario: Scoring an empty directory fails rather than reporting a pass
    Given a prototype output directory
    When I run the command "proto score {output}"
    Then the command exits with code 1
    And the output says no cells were found

  Scenario: A produced run can be rescored and shown
    Given a prototype output directory
    When I run a scripted prototype for task "analysis-de9im-001" in arm "B"
    And I rescore that run
    Then the rescore reports that one of one cells passed the oracle
    And showing the run prints its oracle scores
    When I corrupt and rescore the result
    Then the rescore reports that no cells passed the oracle

  Scenario: Showing a directory with no summary fails
    Given a prototype output directory
    When I run the command "proto show {output}"
    Then the command exits with code 1
    And the output says the summary is missing
